import http.client
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tests.web.test_web import call, site  # noqa: F401
from web import server, state

# --- option injection: text from the browser must never become a flag of the child -------------


@pytest.mark.parametrize("field", ["keywords", "location"])
def test_naukri_search_text_cannot_turn_into_an_option(field):
    with pytest.raises(ValueError, match="cannot start with '-'"):
        state.naukri_command(**{field: "--headless"})
    with pytest.raises(ValueError):
        state.naukri_command(**{field: "  -x"})
    argv = state.naukri_command(**{field: "C++ - senior"}).argv
    assert "C++ - senior" in argv


@pytest.mark.parametrize("field", ["title", "company"])
def test_external_title_and_company_cannot_turn_into_an_option(field):
    with pytest.raises(ValueError):
        state.external_command(url="https://jobs.example/1", **{field: "--headless"})
    argv = state.external_command(url="https://jobs.example/1", **{field: "Acme - Corp"}).argv
    assert argv[argv.index(f"--{field}") + 1] == "Acme - Corp"


def test_linkedin_draft_cannot_turn_into_an_option():
    with pytest.raises(ValueError):
        state.linkedin_command(mode="post", draft="--env /tmp/stolen.env")
    assert state.linkedin_command(mode="post", draft="Hello - world").argv[-1] == "Hello - world"
    assert state.linkedin_command(mode="dry-run", draft="--env x").argv[1:] == ("-m", "linkedin_bot", "--dry-run")


def test_resume_job_file_and_labels_cannot_turn_into_an_option(tmp_path):
    jd = tmp_path / "jd.txt"
    jd.write_text("role")
    with pytest.raises(ValueError):
        state.resume_command(jd_file="--env", must_exist=False)
    with pytest.raises(ValueError):
        state.resume_command(jd_file=str(jd), title="-v")
    with pytest.raises(ValueError):
        state.resume_command(jd_file=str(jd), company="--headless")
    argv = state.resume_command(jd_file=str(jd), title="ML - Eng").argv
    assert argv[argv.index("--tailor") + 1] == str(jd) and "ML - Eng" in argv


def test_the_api_refuses_option_injection_end_to_end(site):
    status, data = call(site, "POST", "/api/preview",
                        {"action": "linkedin", "options": {"mode": "post", "draft": "--env /tmp/x"}})
    assert status == 200 and "cannot start with '-'" in data["needed"]
    status, data = call(site, "POST", "/api/run",
                        {"action": "external", "options": {"url": "https://x.example", "title": "--headless"}})
    assert status == 400 and "cannot start with '-'" in data["error"]
    assert call(site, "GET", "/api/run")[1]["running"] is False


# --- inside(): static files stay inside their folder ---------------------------------------------


def test_inside_refuses_dotfiles_symlinks_and_traversal(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.md").write_text("a")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (root / "link.txt").symlink_to(outside)
    (root / "dir").symlink_to(tmp_path)

    assert server.inside(root, "sub/a.md") == (root / "sub" / "a.md").resolve()
    assert server.inside(root, "") == root.resolve()
    assert server.inside(root, "//sub//a.md") == (root / "sub" / "a.md").resolve()
    assert server.inside(root, ".env") is None
    assert server.inside(root, "sub/.hidden") is None
    assert server.inside(root, "../outside.txt") is None
    assert server.inside(root, "sub/../../outside.txt") is None
    assert server.inside(root, "link.txt") is None
    assert server.inside(root, "dir/outside.txt") is None
    with pytest.raises(ValueError):
        server.inside(root, "sub/a\x00.md")


def test_odd_paths_are_bad_requests_not_crashes(site):
    for path in ("/course/%00", "/reports/a%00b", "/course/%2e%2e%2f%2e%2e%2f.env", "/course/%2f%2fetc%2fpasswd"):
        status, _ = call(site, "GET", path)
        assert status in (400, 404), path


# --- /api/open: only things under data/ ever reach `open` ----------------------------------------


@pytest.fixture
def opened(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "open_outside", calls.append)
    return calls


def test_open_shows_only_files_under_data(site, opened):
    data = state.APPLY / "data"
    (data / "sub").mkdir(parents=True)
    (data / "sub" / "report.html").write_text("<p>hi</p>")
    (state.APPLY / "secret.txt").write_text("no")
    link = data / "escape"
    link.symlink_to(state.APPLY / "secret.txt")

    ok = call(site, "POST", "/api/open", {"what": "path", "path": str(data / "sub" / "report.html")})
    assert ok[0] == 200 and opened == [str((data / "sub" / "report.html").resolve())]

    for bad in (
        str(state.APPLY / "secret.txt"),
        str(data / ".." / "secret.txt"),
        str(data),
        str(link),
        "data/sub/report.html",
        "~/Desktop",
        "",
        str(data / "sub" / "missing.html"),
    ):
        status, body = call(site, "POST", "/api/open", {"what": "path", "path": bad})
        assert status == 400, (bad, body)
    assert call(site, "POST", "/api/open", {"what": "env"})[0] == 400
    assert call(site, "POST", "/api/open", {"what": "path", "path": ["x"]})[0] == 400
    assert len(opened) == 1


def test_open_needs_the_same_site_and_json(site, opened):
    data = state.APPLY / "data"
    data.mkdir()
    (data / "f.txt").write_text("x")
    body = {"what": "path", "path": str(data / "f.txt")}
    assert call(site, "POST", "/api/open", body, headers={"Origin": "https://evil.example"})[0] == 403
    assert call(site, "POST", "/api/open", body, headers={"Host": "evil.example:80"})[0] == 403
    port = site.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/api/open", '{"what":"resumes"}',
                 {"Host": f"127.0.0.1:{port}", "Content-Type": "text/plain"})
    assert conn.getresponse().status == 403
    conn.close()
    assert opened == []


# --- headers and the .env file -------------------------------------------------------------------


def test_every_reply_refuses_to_be_framed_by_other_sites(site):
    port = site.server_address[1]
    for method, path in (("GET", "/api/status"), ("GET", "/course/"), ("GET", "/nope"), ("POST", "/api/stop")):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request(method, path, "{}" if method == "POST" else None,
                     {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"})
        reply = conn.getresponse()
        reply.read()
        assert reply.getheader("X-Frame-Options") == "SAMEORIGIN", (method, path)
        assert reply.getheader("X-Content-Type-Options") == "nosniff"
        conn.close()


def test_the_env_file_is_only_served_to_this_computer(site):
    assert call(site, "GET", "/api/file?name=env", headers={"Host": "evil.example:80"})[0] == 403
    assert call(site, "GET", "/api/file?name=env", headers={"Host": "127.0.0.1:1"})[0] == 403
    status, data = call(site, "GET", "/api/file?name=env")
    assert status == 200 and data["text"] == "SECRET=1\n"
    assert call(site, "GET", "/api/file?name=.env")[0] == 400
    assert call(site, "GET", "/api/file?name=")[0] == 400
