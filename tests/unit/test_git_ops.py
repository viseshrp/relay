import subprocess

from relay.worker.git_ops import create_branch, get_head_commit, is_git_repo


def test_git_repo_detection_and_branch_creation(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("relay\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "relay@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Relay"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    assert is_git_repo(str(repo)) is True
    head = get_head_commit(str(repo))
    assert head
    assert create_branch(str(repo), "relay/test-branch", head) == "relay/test-branch"
