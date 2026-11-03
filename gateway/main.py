import asyncio
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import auth
from auth import GatewayError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway")

# Route prefix -> environment variable holding that service's public URL.
ROUTES = {
    "students": "STUDENT_SERVICE_URL",
    "appointments": "APPOINTMENT_SERVICE_URL",
    "consultations": "CONSULTATION_SERVICE_URL",
    "medicines": "PHARMACY_SERVICE_URL",
    "dispensing": "PHARMACY_SERVICE_URL",
    "inquiries": "PHARMACY_SERVICE_URL",
    "excuses": "EXCUSE_SERVICE_URL",
    "instructors": "EXCUSE_SERVICE_URL",
    "notifications": "NOTIFICATION_SERVICE_URL",
    # /dispense is intentionally not exposed: only the Consultation service calls it.
}
SERVICES = {name: os.environ.get(env, "").rstrip("/") for name, env in ROUTES.items()}

# Role-based access: who may read (GET) and who may change (everything else) each service.
# Students are further limited by STUDENT_RULES below.
STAFF = {"admin", "nurse"}
PERMISSIONS = {
    "students": {"read": STAFF, "write": STAFF},
    "appointments": {"read": STAFF, "write": STAFF},
    "consultations": {"read": STAFF, "write": STAFF},
    "medicines": {"read": STAFF, "write": STAFF},
    "dispensing": {"read": STAFF, "write": STAFF},
    "inquiries": {"read": STAFF | {"student"}, "write": STAFF | {"student"}},
    "excuses": {"read": STAFF | {"student"}, "write": STAFF},
    "instructors": {"read": STAFF, "write": STAFF},
    "notifications": {"read": STAFF, "write": {"admin"}},
}
UUID_RE = r"[0-9a-fA-F-]{36}"
# The only things a student may do (own records only; the service double-checks ownership).
STUDENT_RULES = [
    ("GET", r"inquiries"),
    ("POST", r"inquiries"),
    ("PATCH", rf"inquiries/{UUID_RE}/cancel"),
    ("GET", r"excuses"),
]
STUDENT_LISTS = {"inquiries", "excuses"}      # list endpoints are forced to the student's own records
# Endpoints that only other services may call.
INTERNAL_ONLY = [("POST", r"excuses"), ("POST", r"notifications"), ("PATCH", rf"appointments/{UUID_RE}/complete")]
READ_METHODS = {"GET", "HEAD", "OPTIONS"}

# Free hosts put idle services to sleep (about 1 minute to wake), so wait long enough.
TIMEOUT = httpx.Timeout(90.0, connect=90.0)
MAX_ATTEMPTS = 4
WAKING_STATUSES = {502, 503, 504}
IDEMPOTENT = {"GET", "HEAD", "PUT", "DELETE", "OPTIONS"}
SKIP_HEADERS = {"host", "content-length", "accept-encoding", "authorization", "connection", "keep-alive",
                "transfer-encoding", "upgrade", "te", "trailer", "proxy-authorization", "proxy-authenticate",
                "x-user-id", "x-user-name", "x-user-role", "x-student-id"}  # identity headers are set only by the gateway


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=TIMEOUT)
    await asyncio.to_thread(auth.bootstrap_admin)
    yield
    await app.state.client.aclose()


app = FastAPI(title="Clinic API Gateway", version="2.3.0", lifespan=lifespan)
origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)


def error(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, "details": details})


@app.exception_handler(GatewayError)
async def gateway_error(_: Request, exc: GatewayError):
    return error(exc.status, exc.code, exc.message, exc.details)


def matches(rules: list[tuple[str, str]], method: str, path: str) -> bool:
    return any(m == method and re.fullmatch(pattern, path) for m, pattern in rules)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gateway", "version": "2.3.0"}


@app.get("/warmup")
async def warmup(request: Request):
    """Wake every sleeping service before a demo."""
    async def ping(name: str, base: str):
        if not base:
            return name, "not configured"
        try:
            r = await request.app.state.client.get(f"{base}/health")
            return name, "ok" if r.status_code == 200 else f"status {r.status_code}"
        except httpx.HTTPError as exc:
            return name, f"unreachable ({type(exc).__name__})"

    groups: dict[str, list[str]] = {}
    for name, base in SERVICES.items():
        groups.setdefault(base, []).append(name)

    async def ping_group(base: str, names: list[str]):
        _, status = await ping(names[0], base)
        return {n: status for n in names}

    merged: dict[str, str] = {}
    for result in await asyncio.gather(*(ping_group(b, ns) for b, ns in groups.items())):
        merged.update(result)
    return merged


@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(full_path: str, request: Request):
    path = full_path.strip("/")
    service = path.split("/", 1)[0]
    method = request.method
    if service not in SERVICES:
        return error(404, "UNKNOWN_SERVICE", f"No service registered for '{service}'")
    base = SERVICES[service]
    if not base:
        return error(503, "SERVICE_NOT_CONFIGURED", f"The {service} service URL is not configured")
    if matches(INTERNAL_ONLY, method, path):
        return error(403, "INTERNAL_ONLY", "This endpoint is only available to other services")

    params = dict(request.query_params)
    body = await request.body()
    extra_headers: dict[str, str] = {}
    claims = None
    is_public = method == "GET" and path.startswith("excuses/verify/")  # the QR code check needs no login
    if not is_public:
        if not auth.JWT_SECRET:
            return error(503, "AUTH_NOT_CONFIGURED", "JWT_SECRET is not configured on the gateway")
        claims = auth.read_token(request.headers.get("authorization"))
        if not claims:
            return error(401, "UNAUTHENTICATED", "Please sign in")
        role = claims.get("role")
        rule = PERMISSIONS[service]["read" if method in READ_METHODS else "write"]
        if role not in rule:
            return error(403, "FORBIDDEN", "Your role cannot do this")
        extra_headers = {"x-user-id": claims["sub"], "x-user-role": role, "x-user-name": quote(claims.get("name") or "")}
        if role == "student":
            student_id = claims.get("student_id")
            if not student_id or not matches(STUDENT_RULES, method, path):
                return error(403, "FORBIDDEN", "Students can only send medicine inquiries and view their own inquiries and excuse slips")
            extra_headers["x-student-id"] = student_id
            if method == "GET" and path in STUDENT_LISTS:
                params["student_id"] = student_id                    # always their own records

    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    url = f"{base}/{path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in SKIP_HEADERS}
    headers.update(extra_headers)
    headers["x-request-id"] = request_id

    # Only retry when the request was certainly not processed, unless the method is idempotent.
    retryable = (httpx.ConnectError, httpx.ConnectTimeout)
    if method in IDEMPOTENT:
        retryable += (httpx.ReadTimeout,)

    last_exc = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            upstream = await request.app.state.client.request(method, url, params=params, headers=headers, content=body)
            log.info("%s %s %s role=%s -> %s (attempt %d)", request_id, method, url,
                     claims.get("role") if claims else "public", upstream.status_code, attempt)
            if upstream.status_code in WAKING_STATUSES and method in IDEMPOTENT and attempt < MAX_ATTEMPTS:
                await asyncio.sleep(6 * attempt)
                continue
            return Response(content=upstream.content, status_code=upstream.status_code,
                            media_type=upstream.headers.get("content-type"), headers={"x-request-id": request_id})
        except retryable as exc:
            last_exc = exc
            log.warning("%s %s failed (%s), attempt %d/%d", request_id, url, type(exc).__name__, attempt, MAX_ATTEMPTS)
            await asyncio.sleep(2 ** attempt)
        except httpx.HTTPError as exc:
            last_exc = exc
            break

    return error(503, "UPSTREAM_UNAVAILABLE", f"The {service} service is not responding",
                 {"request_id": request_id, "reason": type(last_exc).__name__})
