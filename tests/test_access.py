"""Roles, product licenses and the SQLite license store. All users here are fake."""
import pytest

from src.access import AccessStore, Principal
from src.llm import load_config

CFG = load_config()


def payload(level, product):
    return {"access_level": level, "product": product}


def test_public_reads_only_public_of_every_product():
    p = Principal.public()
    assert all(p.allows(payload("public", prod), CFG) for prod in ("kubernetes", "github"))
    assert not p.allows(payload("internal", "github"), CFG) and not p.allows(payload("restricted", "github"), CFG)


def test_member_license_unlocks_internal_and_restricted_for_that_product_only():
    m = Principal.member("github")
    assert m.allows(payload("internal", "github"), CFG) and m.allows(payload("restricted", "github"), CFG)
    assert m.allows(payload("public", "kubernetes"), CFG)  # public docs stay open for every product
    assert not m.allows(payload("internal", "kubernetes"), CFG)
    assert not m.allows(payload("restricted", "kubernetes"), CFG)


def test_admin_reads_everything_but_missing_data_is_denied_even_for_admin():
    a = Principal.admin()
    assert all(a.allows(payload(lv, "kafka"), CFG) for lv in ("public", "internal", "restricted"))
    assert not a.allows({"product": "kafka"}, CFG)  # no access_level -> denied
    assert not a.allows(payload("secret-level", "kafka"), CFG)  # unknown level -> denied
    assert not Principal.member("kafka").allows({"access_level": "internal"}, CFG)  # no product -> denied


def test_bad_roles_and_products_fail_closed():
    with pytest.raises(ValueError, match="unknown role"):
        Principal("root")
    with pytest.raises(ValueError, match="unknown product"):
        Principal.member("oracle")
    with pytest.raises(ValueError, match="no licenses"):
        Principal("public", frozenset({"github"}))


@pytest.fixture
def store():
    s = AccessStore(":memory:")
    s.bootstrap_admin("admin-1")
    s.add_user("admin-1", "alice")  # fake members
    s.add_user("admin-1", "bob")
    return s


def test_admin_grants_and_member_gets_exactly_those_licenses(store):
    store.grant("admin-1", "alice", "github")
    assert store.principal("alice") == Principal.member("github")
    assert store.principal("bob") == Principal.member()  # no license yet
    assert store.principal("admin-1") == Principal.admin()


def test_revoke_takes_effect_immediately(store):
    store.grant("admin-1", "alice", "github")
    store.grant("admin-1", "alice", "kafka")
    store.revoke("admin-1", "alice", "github")
    assert store.principal("alice").licenses == frozenset({"kafka"})


def test_only_admins_can_change_licenses_or_users(store):
    with pytest.raises(PermissionError):
        store.grant("alice", "alice", "github")  # a member cannot self-grant
    with pytest.raises(PermissionError):
        store.revoke("bob", "alice", "github")
    with pytest.raises(PermissionError):
        store.add_user("alice", "mallory", "admin")
    with pytest.raises(PermissionError):
        store.grant("nobody", "alice", "github")  # unknown actor
    assert store.licenses_of("alice") == []


def test_unknown_or_missing_user_is_public_and_bad_grants_are_rejected(store):
    assert store.principal("ghost") == Principal.public() and store.principal(None) == Principal.public()
    with pytest.raises(ValueError, match="unknown product"):
        store.grant("admin-1", "alice", "oracle")
    with pytest.raises(ValueError, match="not a member"):
        store.grant("admin-1", "admin-1", "github")
    with pytest.raises(ValueError, match="not a member"):
        store.grant("admin-1", "ghost", "github")


def test_every_change_is_in_the_audit_log(store):
    store.grant("admin-1", "alice", "github")
    store.revoke("admin-1", "alice", "github")
    actions = [(a, act, u, prod) for _, a, act, u, prod in store.audit_log()]
    assert ("admin-1", "grant", "alice", "github") in actions and ("admin-1", "revoke", "alice", "github") in actions
    assert ("setup", "bootstrap_admin", "admin-1", None) in actions


def test_grant_twice_is_harmless(store):
    store.grant("admin-1", "alice", "github")
    store.grant("admin-1", "alice", "github")
    assert store.licenses_of("alice") == ["github"]
