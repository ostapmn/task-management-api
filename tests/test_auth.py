async def test_register_login_me(client):
    r = await client.post("/auth/register", json={"email": "A@Example.com", "password": "password123"})
    assert r.status_code == 201
    assert r.json()["email"] == "a@example.com"
    assert "password" not in r.text

    login = await client.post("/auth/login", data={"username": "a@example.com", "password": "password123"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == "a@example.com"


async def test_duplicate_email_conflict(client):
    body = {"email": "dup@example.com", "password": "password123"}
    assert (await client.post("/auth/register", json=body)).status_code == 201
    assert (await client.post("/auth/register", json=body)).status_code == 409


async def test_short_password_rejected(client):
    r = await client.post("/auth/register", json={"email": "x@example.com", "password": "short"})
    assert r.status_code == 422


async def test_wrong_password_and_missing_token(client):
    await client.post("/auth/register", json={"email": "w@example.com", "password": "password123"})
    bad = await client.post("/auth/login", data={"username": "w@example.com", "password": "nope-nope"})
    assert bad.status_code == 401
    assert (await client.get("/tasks")).status_code == 401
    assert (await client.get("/tasks", headers={"Authorization": "Bearer garbage"})).status_code == 401
