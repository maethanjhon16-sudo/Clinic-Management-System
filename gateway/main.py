import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

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
    "doctors": "APPOINTMENT_SERVICE_URL",
    "consultations": "CONSULTATION_SERVICE_URL",
    "medicines": "PHARMACY_SERVICE_URL",
    "dispensing": "PHARMACY_SERVICE_URL",
    "excuses": "EXCUSE_SERVICE_URL",
    "notifications": "NOTIFICATION_SERVICE_URL",
    # /dispense is intentionally not exposed: only the Consultation service calls it.
}
SERVICES = {name: os.environ.get(env, "").rstrip("/") for name, env in ROUTES.items()}

# Role-based access: who may read (GET) and who may change (everything else) each service.
STAFF = {"admin", "doctor", "nurse"}
PERMISSIONS = {
    "students": {"read": STAFF, "write": {"admin", "nurse"}},
    "doctors": {"read": STAFF, "write": {"admin"}},
    "appointments": {"read": STAFF | {"student"}, "write": STAFF},
    "consultations": {"read": STAFF, "write": {"admin", "doctor"}},
    "medicines": {"read": STAFF, "write": {"admin", "nurse"}},
    "dispensing": {"read": STAFF, "write": {"admin", "nurse"}},
    "excuses": {"read": STAFF | {"student"}, "write": STAFF},
    "notifications": {"read": STAFF, "write": {"admin"}},
}
INTERNAL_ONLY = {("POST", "excuses"), ("POST", "notifications")}  # only other services may create these
STUDENT_LISTS = {"appointments", "excuses"}                         # the only places a student may look, own records only
READ_METHODS = {"GET", "HEAD", "OPTIONS"}

# Free hosts put idle services to sleep (about 1 minute to wake), so wait long enough.
TIMEOUT = httpx.Timeout(90.0, connect=90.0)
MAX_ATTEMPTS = 4
WAKING_STATUSES = {502, 503, 504}
IDEMPOTENT = {"GET", "HEAD", "PUT", "DELETE", "OPTIONS"}
SKIP_HEADERS = {"host", "content-length", "accept-encoding", "authorization", "connection", "keep-alive",
                "transfer-encoding", "upgrade", "te", "trailer", "proxy-authorization", "proxy-authenticate"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=TIMEOUT)
    await asyncio.to_thread(auth.bootstrap_admin)
    yield
    await app.state.client.aclose()


app = FastAPI(title="Clinic API Gateway", version="1.0.0", lifespan=lifespan)
origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)


def error(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, "details": details})


@app.exception_handler(GatewayError)
async def gateway_error(_: Request, exc: GatewayError):
    return error(exc.status, exc.code, exc.message, exc.details)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gateway", "version": "2.0.0"}


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
    service = full_path.split("/", 1)[0]
    method = request.method
    if service not in SERVICES:
        return error(404, "UNKNOWN_SERVICE", f"No service registered for '{service}'")
    base = SERVICES[service]
    if not base:
        return error(503, "SERVICE_NOT_CONFIGURED", f"The {service} service URL is not configured")
    if (method, full_path.rstrip("/")) in INTERNAL_ONLY:
        return error(403, "INTERNAL_ONLY", "This endpoint is only available to other services")

    params = dict(request.query_params)
    claims = None
    is_public = method == "GET" and full_path.startswith("excuses/verify/")  # the QR code check needs no login
    if not is_public:
        if not auth.JWT_SECRET:
            return error(503, "AUTH_NOT_CONFIGURED", "JWT_SECRET is not configured on the gateway")
        claims = auth.read_token(request.headers.get("authorization"))
        if not claims:
            return error(401, "UNAUTHENTICATED", "Please sign in")
        role = claims.get("role")
        rule = PERMISSIONS[service]["read" if method in READ_METHODS else "write"]
        if role not in rule:
            return error(403, "FORBIDDEN", f"The {role} role cannot do this")
        if role == "student":  # students only see their own records, through the list endpoints
            if method != "GET" or full_path.rstrip("/") not in STUDENT_LISTS or not claims.get("student_id"):
                return error(403, "FORBIDDEN", "Students can only view their own records")
            params["student_id"] = claims["student_id"]

    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    url = f"{base}/{full_path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in SKIP_HEADERS}
    headers["x-request-id"] = request_id
    body = await request.body()

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
