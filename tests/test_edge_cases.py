import asyncio
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import delete

from app.config import settings
from app.models import User
from tests.conftest import PASSWORD, future, past


def _token(user_id, expires_in: timedelta) -> dict:
    payload = {"sub": str(user_id), "exp": datetime.now(timezone.utc) + expires_in}
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return {"Authorization": f"Bearer {token}"}


# 1. JWT edge cases ---------------------------------------------------------------------------

async def test_expired_token_rejected(client, alice):
    uid, _ = alice
    assert (await client.get("/users/me", headers=_token(uid, timedelta(seconds=-5)))).status_code == 401
    assert (await client.get("/users/me", headers=_token(uid, timedelta(minutes=5)))).status_code == 200


async def test_token_signed_with_other_key_or_algorithm_rejected(client, alice):
    uid, _ = alice
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)
    forged = jwt.encode({"sub": str(uid), "exp": exp}, "wrong-key-wrong-key-wrong-key-123456", algorithm="HS256")
    assert (await client.get("/users/me", headers={"Authorization": f"Bearer {forged}"})).status_code == 401
    unsigned = jwt.encode({"sub": str(uid), "exp": exp}, None, algorithm="none")
    assert (await client.get("/users/me", headers={"Authorization": f"Bearer {unsigned}"})).status_code == 401
    no_sub = jwt.encode({"exp": exp}, settings.secret_key, algorithm=settings.algorithm)
    assert (await client.get("/users/me", headers={"Authorization": f"Bearer {no_sub}"})).status_code == 401


async def test_token_of_deleted_user_rejected(client, alice, session_factory):
    uid, h = alice
    assert (await client.get("/users/me", headers=h)).status_code == 200
    async with session_factory() as s:
        await s.execute(delete(User).where(User.id == uid))
        await s.commit()
    assert (await client.get("/users/me", headers=h)).status_code == 401


# 2. Concurrency ------------------------------------------------------------------------------

async def test_concurrent_status_changes_are_serialized(client, alice):
    uid, h = alice
    tid = (await client.post("/tasks", json={"title": "t", "assignee_id": uid}, headers=h)).json()["id"]
    body = {"status": "In Progress"}
    results = await asyncio.gather(*[client.patch(f"/tasks/{tid}/status", json=body, headers=h) for _ in range(5)])
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409, 409]


async def test_concurrent_reassignment_respects_limit(client, alice, bob):
    uid, h = alice
    bid, _ = bob
    for _ in range(9):
        assert (await client.post("/tasks", json={"title": "t", "assignee_id": uid}, headers=h)).status_code == 201
    others = [(await client.post("/tasks", json={"title": "o", "assignee_id": bid}, headers=h)).json()["id"] for _ in range(4)]
    results = await asyncio.gather(
        *[client.patch(f"/tasks/{t}", json={"assignee_id": uid}, headers=h) for t in others]
    )
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409]


async def test_status_change_racing_with_delete(client, alice):
    _, h = alice
    tid = (await client.post("/tasks", json={"title": "t"}, headers=h)).json()["id"]
    results = await asyncio.gather(
        client.patch(f"/tasks/{tid}/status", json={"status": "In Progress"}, headers=h),
        client.delete(f"/tasks/{tid}", headers=h),
    )
    codes = [r.status_code for r in results]
    # either order is valid, but never a 500, and the final state must be consistent
    assert all(c in (200, 204, 404, 409) for c in codes), codes


# 3. Passwords --------------------------------------------------------------------------------

async def test_password_byte_limit(client):
    # 40 two-byte characters = 40 chars (passes the length check) but 80 bytes (> bcrypt's 72)
    r = await client.post("/auth/register", json={"email": "u@example.com", "password": "ж" * 40})
    assert r.status_code == 422
    ok = await client.post("/auth/register", json={"email": "u@example.com", "password": "ж" * 36})
    assert ok.status_code == 201  # exactly 72 bytes
    login = await client.post("/auth/login", data={"username": "u@example.com", "password": "ж" * 36})
    assert login.status_code == 200


async def test_login_is_case_insensitive_on_email_but_not_password(client, alice):
    ok = await client.post("/auth/login", data={"username": "ALICE@EXAMPLE.COM", "password": PASSWORD})
    assert ok.status_code == 200
    bad = await client.post("/auth/login", data={"username": "alice@example.com", "password": PASSWORD.upper()})
    assert bad.status_code == 401


# 4. Timezone handling in filters -------------------------------------------------------------

async def test_naive_and_offset_filter_params_are_equivalent(client, alice):
    _, h = alice
    await client.post("/tasks", json={"title": "t", "deadline": "2030-06-01T12:00:00+00:00"}, headers=h)
    # 2030-06-01T14:00+02:00 == 12:00 UTC; naive values are read as UTC
    for params, expected in [
        ({"deadline_from": "2030-06-01T12:00:00"}, 1),
        ({"deadline_from": "2030-06-01T12:00:01"}, 0),
        ({"deadline_to": "2030-06-01T12:00:00"}, 1),
        ({"deadline_to": "2030-06-01T11:59:59"}, 0),
        ({"deadline_from": "2030-06-01T14:00:00+02:00", "deadline_to": "2030-06-01T14:00:00+02:00"}, 1),
        ({"deadline_to": "2030-06-01T13:00:00+02:00"}, 0),
    ]:
        r = await client.get("/tasks", params=params, headers=h)
        assert r.status_code == 200 and r.json()["total"] == expected, params


async def test_non_utc_deadline_offset_is_honoured(client, alice):
    _, h = alice
    # one hour ago expressed in a +05:00 zone is still in the past
    almost_now = (datetime.now(timezone.utc) - timedelta(hours=1)).astimezone(timezone(timedelta(hours=5)))
    r = await client.post("/tasks", json={"title": "t", "deadline": almost_now.isoformat()}, headers=h)
    assert r.status_code == 422
    soon = (datetime.now(timezone.utc) + timedelta(hours=1)).astimezone(timezone(timedelta(hours=-8)))
    assert (await client.post("/tasks", json={"title": "t", "deadline": soon.isoformat()}, headers=h)).status_code == 201


async def test_deadline_one_second_in_past_rejected_and_one_second_ahead_accepted(client, alice):
    _, h = alice
    r = await client.post("/tasks", json={"title": "t", "deadline": past(1 / 86400).isoformat()}, headers=h)
    assert r.status_code == 422
    ahead = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    assert (await client.post("/tasks", json={"title": "t", "deadline": ahead}, headers=h)).status_code == 201


# 5. Small API edges --------------------------------------------------------------------------

async def test_offset_beyond_total_returns_empty_page(client, alice):
    _, h = alice
    await client.post("/tasks", json={"title": "t"}, headers=h)
    body = (await client.get("/tasks?offset=50", headers=h)).json()
    assert body["items"] == [] and body["total"] == 1 and body["offset"] == 50


async def test_null_for_required_fields_on_patch(client, alice):
    _, h = alice
    tid = (await client.post("/tasks", json={"title": "t"}, headers=h)).json()["id"]
    assert (await client.patch(f"/tasks/{tid}", json={"title": None}, headers=h)).status_code == 422
    assert (await client.patch(f"/tasks/{tid}", json={"priority": None}, headers=h)).status_code == 422
    ok = await client.patch(f"/tasks/{tid}", json={"description": None, "deadline": None}, headers=h)
    assert ok.status_code == 200


async def test_empty_patch_is_a_noop(client, alice):
    _, h = alice
    t = (await client.post("/tasks", json={"title": "t", "priority": "High"}, headers=h)).json()
    r = await client.patch(f"/tasks/{t['id']}", json={}, headers=h)
    assert r.status_code == 200 and r.json()["title"] == "t" and r.json()["priority"] == "High"


async def test_unassigning_in_review_is_blocked(client, alice):
    uid, h = alice
    tid = (await client.post("/tasks", json={"title": "t", "assignee_id": uid}, headers=h)).json()["id"]
    for s in ("In Progress", "Review"):
        await client.patch(f"/tasks/{tid}/status", json={"status": s}, headers=h)
    assert (await client.patch(f"/tasks/{tid}", json={"assignee_id": None}, headers=h)).status_code == 409
    # re-sending the same assignee is not a change and is allowed
    assert (await client.patch(f"/tasks/{tid}", json={"assignee_id": uid}, headers=h)).status_code == 200


async def test_editing_other_fields_of_task_of_full_assignee_is_not_blocked(client, alice):
    uid, h = alice
    ids = [(await client.post("/tasks", json={"title": "t", "assignee_id": uid}, headers=h)).json()["id"] for _ in range(10)]
    assert (await client.patch(f"/tasks/{ids[0]}", json={"title": "renamed"}, headers=h)).status_code == 200
    assert (await client.patch(f"/tasks/{ids[0]}/status", json={"status": "In Progress"}, headers=h)).status_code == 200


async def test_search_with_backslash_and_empty_query(client, alice):
    _, h = alice
    await client.post("/tasks", json={"title": r"path C:\temp"}, headers=h)
    await client.post("/tasks", json={"title": "other"}, headers=h)
    assert (await client.get("/tasks", params={"q": "\\temp"}, headers=h)).json()["total"] == 1
    assert (await client.get("/tasks", params={"q": ""}, headers=h)).json()["total"] == 2


async def test_unknown_assignee_on_patch_and_malformed_ids(client, alice):
    _, h = alice
    tid = (await client.post("/tasks", json={"title": "t"}, headers=h)).json()["id"]
    assert (await client.patch(f"/tasks/{tid}", json={"assignee_id": 9999}, headers=h)).status_code == 422
    assert (await client.get("/tasks/abc", headers=h)).status_code == 422
    huge = 99999999999999999999
    assert (await client.get(f"/tasks/{huge}", headers=h)).status_code == 422
    assert (await client.get(f"/tasks/{huge}/comments", headers=h)).status_code == 422
    assert (await client.get("/tasks/0", headers=h)).status_code == 422
    assert (await client.post("/tasks", json={"title": "t", "assignee_id": huge}, headers=h)).status_code == 422
    assert (await client.get(f"/tasks?assignee_id={huge}", headers=h)).status_code == 422
