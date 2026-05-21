from app.main import app
from app.services.audit.function_audit import audit_routes, api_routes, route_key


def test_all_api_routes_are_classified_for_full_function_audit():
    routes = audit_routes(app)
    uncategorized = [route_key(route) for route in routes if route.category == "uncategorized"]

    assert len(routes) == len(api_routes(app))
    assert uncategorized == []


def test_live_runnable_audit_routes_are_read_only_or_protected_reads():
    live_routes = [route for route in audit_routes(app) if route.runnable_live]

    assert live_routes
    assert all(route.method == "GET" or route.path == "/api/parts/find" for route in live_routes)
    assert all(route.category in {"read", "protected_read"} for route in live_routes)


def test_mutating_or_external_routes_have_skip_reasons():
    skipped = [route for route in audit_routes(app) if not route.runnable_live]

    assert skipped
    assert all(route.reason for route in skipped)
    assert all(route.category != "uncategorized" for route in skipped)
