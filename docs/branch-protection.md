# Enterprise GitHub Branch Protection & Governance Standards

This document establishes the official branch protection policies, security controls, and merge governance requirements for the `aws-cloud-workflow-orchestrator` repository.

---

## 1. Protected Branch Strategy

| Branch | Classification | Purpose | Merge Method |
| :--- | :--- | :--- | :--- |
| `main` | Production Protected | Represents deployable, validated production releases | Squash & Merge |
| `develop` | Integration Protected | Shared staging branch integrating validated features | Squash & Merge / Rebase |
| `feature/*` | Ephemeral | Active development branches created by engineers | Fast-forward / Rebase |
| `hotfix/*` | Critical Fixes | Expedited patches directly targeting `main` | Squash & Merge |

---

## 2. Core Protection Policies (Enforced on `main` and `develop`)

### A. Pull Request Verification
1. **Require Pull Request**: Direct pushes (`git push origin main`) are strictly denied for all contributors and administrators.
2. **Approval Threshold**: Minimum of **1 approving review** from a designated code maintainer is required before a PR can be merged.
3. **Dismiss Stale Approvals**: Any subsequent commit pushed to an open pull request invalidates previous approvals, requiring re-review.
4. **Conversation Resolution**: All review comments and discussions must be marked as resolved prior to merging.

### B. Required Status Checks (CI/CD Gates)
All automated continuous integration checks defined in [.github/workflows/ci.yml](file:///c:/Users/harsh/OneDrive/Desktop/aws-cloud-workflow-orchestrator/.github/workflows/ci.yml) must report `SUCCESS` before merge eligibility:
- `lint-and-code-style` (Ruff linter and formatting validator)
- `security-sast` (Bandit AST static analysis & safety dependency audit)
- `backend-tests` (Full Pytest suite with PostgreSQL, Redis & LocalStack service containers; minimum 85% test coverage gate)
- `resilience-and-chaos-testing` (Chaos engineering simulator: S3 faults, DynamoDB throttles, Redis drop, worker crashes)
- `docker-image-build` (Production Docker Compose syntax & multi-stage container build validation)

### C. Commit Integrity & History Hygiene
1. **Require Signed Commits**: All commits must be cryptographically signed with GPG or SSH keys.
2. **Require Linear History**: Merge commits are forbidden; Git history is preserved linearly via squash merges.
3. **Prevent Force Pushes**: `git push --force` or `--force-with-lease` is permanently disabled on protected branches.
4. **Prevent Branch Deletion**: Protected branches cannot be accidentally deleted via CLI or GitHub UI.
5. **Enforce for Administrators**: Repository administrators and team leads are subject to the same strict evaluation rules.

---

## 3. GitHub CLI Configuration Command

To programmatically apply these protection rules to your repository using the GitHub CLI (`gh`), execute:

```bash
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  /repos/{owner}/{repo}/branches/main/protection \
  -f required_status_checks[strict]=true \
  -f required_status_checks[contexts][]=lint-and-code-style \
  -f required_status_checks[contexts][]=security-sast \
  -f required_status_checks[contexts][]=backend-tests \
  -f required_status_checks[contexts][]=resilience-and-chaos-testing \
  -f required_status_checks[contexts][]=docker-image-build \
  -f enforce_admins=true \
  -f required_pull_request_reviews[dismiss_stale_reviews]=true \
  -f required_pull_request_reviews[require_code_owner_reviews]=true \
  -f required_pull_request_reviews[required_approving_review_count]=1 \
  -f required_linear_history=true \
  -f allow_force_pushes=false \
  -f allow_deletions=false
```

---

## 4. Local Pre-Commit Guardrails

Before pushing any commits upstream, developers must ensure the automated pre-commit hooks are installed locally:

```bash
# Install pre-commit framework
pip install pre-commit

# Install git hook scripts
pre-commit install

# Manually execute against all files
pre-commit run --all-files
```
Hooks configured in [.pre-commit-config.yaml](file:///c:/Users/harsh/OneDrive/Desktop/aws-cloud-workflow-orchestrator/.pre-commit-config.yaml) ensure code formatting, AST security analysis, and secret leak detection happen prior to code leaving developer workstations.
