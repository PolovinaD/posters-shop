#!/usr/bin/env python3
"""Offline structural validation of the GitHub Actions workflows.

Run from the repository root:

    python3 .github/workflows/validate-workflows.py

This is a substitute for tooling that is not available in this environment
(`actionlint`, `gh`). It validates the *structure* of the two workflow files
and their agreement with `deploy/charts/` and `deploy/full-deploy.sh`.

WHAT THIS CANNOT CHECK. It is strictly offline and has no view of GitHub-side
state. It cannot tell you whether the repository variables (AWS_ACCOUNT_ID,
AWS_REGION, EKS_CLUSTER), the OIDC identity provider, the `github-actions-role`
trust policy, GitHub Environments, or ECR repositories actually exist or are
correct. Those remain operator prerequisites -- see deploy/README.md.

For a fuller lint of Actions syntax (optional, not required by this script):

    brew install actionlint && actionlint .github/workflows/*.yaml

NOTE ON PyYAML: PyYAML implements YAML 1.1, in which the bare key `on:` parses
as the boolean True, not the string 'on'. Every read of the trigger block must
therefore use `d.get('on', d.get(True))`. Getting this wrong makes every
trigger assertion silently vacuous.
"""

import os
import re
import sys

import yaml

BUILD = ".github/workflows/build-and-push.yaml"
DEPLOY = ".github/workflows/deploy.yaml"
CHARTS_DIR = "deploy/charts"
FULL_DEPLOY = "deploy/full-deploy.sh"

FAILURES = []


def fail(group, msg):
    FAILURES.append("[%s] %s" % (group, msg))


def triggers(doc, path):
    """Read the trigger block, handling the YAML 1.1 `on:` -> True gotcha."""
    on = doc.get("on", doc.get(True))
    if on is None:
        fail("1 parse", "%s: no trigger block found (checked both 'on' and True keys)" % path)
        return {}
    if not isinstance(on, dict):
        fail("1 parse", "%s: trigger block is %s, expected a mapping" % (path, type(on).__name__))
        return {}
    return on


def load(path):
    try:
        with open(path) as fh:
            doc = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001
        fail("1 parse", "%s: YAML parse error: %s" % (path, exc))
        return None
    if not isinstance(doc, dict):
        fail("1 parse", "%s: top level is %s, expected a mapping" % (path, type(doc).__name__))
        return None
    return doc


def text(path):
    with open(path) as fh:
        return fh.read()


def join_continuations(block):
    """Join backslash-continued shell lines into single logical lines."""
    out, buf = [], ""
    for line in block.splitlines():
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
        else:
            out.append(buf + line)
            buf = ""
    if buf:
        out.append(buf)
    return out


def steps_of(doc, job):
    return (doc.get("jobs", {}).get(job, {}) or {}).get("steps", []) or []


def find_step(doc, job, pred):
    for idx, step in enumerate(steps_of(doc, job)):
        if pred(step):
            return idx, step
    return -1, None


def dispatch_service_options(on, path):
    inputs = (on.get("workflow_dispatch") or {}).get("inputs") or {}
    svc = inputs.get("service")
    if not svc:
        fail("3 parity", "%s: workflow_dispatch has no `service` input" % path)
        return None
    opts = svc.get("options")
    if not opts:
        fail("3 parity", "%s: workflow_dispatch `service` input has no options" % path)
        return None
    return opts


def main():
    build = load(BUILD)
    deploy = load(DEPLOY)
    if build is None or deploy is None:
        report()
        return

    build_on = triggers(build, BUILD)
    deploy_on = triggers(deploy, DEPLOY)
    build_txt = text(BUILD)
    deploy_txt = text(DEPLOY)

    # ---- 2. B1: push trigger targets master; no `main` branch anywhere -----
    push = build_on.get("push") or {}
    branches = push.get("branches")
    if branches != ["master"]:
        fail("2 B1", "%s: on.push.branches is %r, expected ['master'] "
                     "(the repo has no `main` branch)" % (BUILD, branches))
    for path, on in ((BUILD, build_on), (DEPLOY, deploy_on)):
        for trig, cfg in on.items():
            if isinstance(cfg, dict) and "main" in (cfg.get("branches") or []):
                fail("2 B1", "%s: trigger %r still lists branch 'main', which does not "
                             "exist on the remote" % (path, trig))

    # ---- 3. B2 / D-3: service-list parity with deploy/charts/ --------------
    charts = sorted(
        d for d in os.listdir(CHARTS_DIR)
        if os.path.isdir(os.path.join(CHARTS_DIR, d))
    )
    if "notifications" not in charts:
        fail("3 parity", "%s: `notifications` chart is missing" % CHARTS_DIR)

    for path, on in ((BUILD, build_on), (DEPLOY, deploy_on)):
        opts = dispatch_service_options(on, path)
        if opts is None:
            continue
        if "all" not in opts:
            fail("3 parity", "%s: workflow_dispatch `service` options lack 'all'" % path)
        listed = sorted(o for o in opts if o != "all")
        if listed != charts:
            fail("3 parity",
                 "%s: workflow_dispatch `service` options do not match %s/\n"
                 "        missing from workflow: %s\n"
                 "        not a chart:           %s"
                 % (path, CHARTS_DIR,
                    sorted(set(charts) - set(listed)) or "none",
                    sorted(set(listed) - set(charts)) or "none"))

    # locate SERVICES="..." by regex; line numbers drift
    fd_txt = text(FULL_DEPLOY)
    m = re.search(r'^\s*SERVICES="([^"]*)"', fd_txt, re.MULTILINE)
    if not m:
        fail("3 parity", '%s: no `SERVICES="..."` assignment found' % FULL_DEPLOY)
    else:
        fd_services = sorted(m.group(1).split())
        if fd_services != charts:
            fail("3 parity",
                 "%s SERVICES= does not match %s/\n"
                 "        missing from full-deploy.sh: %s\n"
                 "        not a chart:                 %s"
                 % (FULL_DEPLOY, CHARTS_DIR,
                    sorted(set(charts) - set(fd_services)) or "none",
                    sorted(set(fd_services) - set(charts)) or "none"))

    # ---- 4. D-1: deploy.yaml trigger shape --------------------------------
    if "workflow_call" not in deploy_on:
        fail("4 D-1", "%s: missing `workflow_call` - it cannot be called by the "
                      "build workflow" % DEPLOY)
    if "workflow_dispatch" not in deploy_on:
        fail("4 D-1", "%s: lost `workflow_dispatch` - manual deploys would break" % DEPLOY)
    if "workflow_run" in deploy_on:
        fail("4 D-1", "%s: `workflow_run` trigger is still present - it is the shared "
                      "root cause of the wrong-tag/wrong-namespace defects" % DEPLOY)

    # ---- 5. Caller/callee input contract (D-2, highest-risk seam) ----------
    call_inputs = (deploy_on.get("workflow_call") or {}).get("inputs") or {}
    caller_job = None
    for name, job in (build.get("jobs") or {}).items():
        if isinstance(job, dict) and job.get("uses") == "./.github/workflows/deploy.yaml":
            caller_job = (name, job)
            break
    if caller_job is None:
        fail("5 contract", "%s: no job with `uses: ./.github/workflows/deploy.yaml` - "
                           "the build->deploy handoff is missing" % BUILD)
    else:
        cname, cjob = caller_job
        with_ = cjob.get("with") or {}
        for key in with_:
            if key not in call_inputs:
                fail("5 contract",
                     "%s job %r passes `with.%s`, which is NOT declared in %s "
                     "workflow_call.inputs (declared: %s)"
                     % (BUILD, cname, key, DEPLOY, sorted(call_inputs)))
        for key, spec in call_inputs.items():
            if isinstance(spec, dict) and spec.get("required") and key not in with_:
                fail("5 contract",
                     "%s workflow_call input %r is required but job %r does not pass it "
                     "(passes: %s)" % (DEPLOY, key, cname, sorted(with_)))
        svc_val = str(with_.get("services", ""))
        if "services_list" not in svc_val:
            fail("5 contract",
                 "%s job %r passes services=%r; it must reference `services_list` "
                 "(a space-separated string). workflow_call inputs cannot be arrays."
                 % (BUILD, cname, svc_val))
        if "services_json" in svc_val:
            fail("5 contract",
                 "%s job %r passes the JSON matrix value to the `services` input "
                 "(%r); the deploy side iterates it with `for svc in $SERVICES`."
                 % (BUILD, cname, svc_val))

    # ---- 6. Job-output references resolve ---------------------------------
    ref = re.compile(r"needs\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)")
    jobs = build.get("jobs") or {}
    for jname, job in jobs.items():
        if not isinstance(job, dict):
            continue
        needs = job.get("needs") or []
        if isinstance(needs, str):
            needs = [needs]
        blob = yaml.safe_dump(job, default_flow_style=False)
        for dep, out in set(ref.findall(blob)):
            if dep not in jobs:
                fail("6 outputs", "%s job %r references needs.%s.outputs.%s but job %r "
                                  "does not exist" % (BUILD, jname, dep, out, dep))
                continue
            if dep not in needs:
                fail("6 outputs", "%s job %r references needs.%s.outputs.%s but %r is not "
                                  "in its `needs` (%s)" % (BUILD, jname, dep, out, dep, needs))
            declared = (jobs[dep] or {}).get("outputs") or {}
            if out not in declared:
                fail("6 outputs",
                     "%s job %r references needs.%s.outputs.%s, which job %r does NOT "
                     "declare (declares: %s). In GitHub Actions this silently evaluates "
                     "to an empty string." % (BUILD, jname, dep, out, dep, sorted(declared)))

    # ---- 7. B4: postershop-staging confined to the dispatch branch --------
    ns_input = call_inputs.get("namespace") or {}
    if ns_input.get("default") != "postershop":
        fail("7 B4", "%s: workflow_call `namespace` default is %r, expected 'postershop' "
                     "(postershop-staging has no secrets or DB wiring)"
             % (DEPLOY, ns_input.get("default")))
    _, resolve_step = find_step(deploy, "deploy", lambda s: s.get("id") == "resolve")
    if resolve_step is None:
        fail("7 B4", "%s: no step with `id: resolve` in the deploy job" % DEPLOY)
    else:
        resolve_run = resolve_step.get("run", "")
        total = deploy_txt.count("postershop-staging")
        inside = resolve_run.count("postershop-staging")
        if total != inside:
            fail("7 B4",
                 "%s: 'postershop-staging' appears %d time(s) in the file but only %d "
                 "inside the resolve step. It must appear ONLY in the workflow_dispatch "
                 "branch of the resolve step - automatic deploys go to `postershop`."
                 % (DEPLOY, total, inside))
        if inside and "workflow_dispatch" not in resolve_run:
            fail("7 B4", "%s: the resolve step mentions postershop-staging but has no "
                         "workflow_dispatch guard around it" % DEPLOY)

    # ---- 8. D-5: no false-green vector on helm ----------------------------
    for lineno, line in enumerate(join_continuations(deploy_txt), 1):
        if "helm upgrade" in line and "|| true" in line:
            fail("8 D-5", "%s:~%d: `helm upgrade` is guarded with `|| true`, which would "
                          "turn a real rollout failure into a green run:\n        %s"
                 % (DEPLOY, lineno, line.strip()))
    for job_name, job in (deploy.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        if job.get("continue-on-error") in (True, "true"):
            fail("8 D-5", "%s job %r sets continue-on-error" % (DEPLOY, job_name))
        for step in job.get("steps") or []:
            if step.get("continue-on-error") in (True, "true"):
                fail("8 D-5", "%s job %r step %r sets continue-on-error, which masks "
                              "deploy failures" % (DEPLOY, job_name, step.get("name")))

    # ---- 9. S1: real push range, full history -----------------------------
    if "HEAD~1" in build_txt:
        fail("9 S1", "%s: still uses HEAD~1; a multi-commit push would examine only the "
                     "tip commit" % BUILD)
    idx, co = find_step(build, "detect-changes",
                        lambda s: "actions/checkout" in str(s.get("uses", "")))
    if co is None:
        fail("9 S1", "%s: detect-changes has no checkout step" % BUILD)
    else:
        depth = (co.get("with") or {}).get("fetch-depth")
        if depth != 0:
            fail("9 S1", "%s: detect-changes checkout fetch-depth is %r, expected 0 "
                         "(a long push range needs full history)" % (BUILD, depth))

    # ---- 10. Probe errexit guard (regression test) ------------------------
    _, probe = find_step(deploy, "deploy", lambda s: s.get("id") == "probe")
    if probe is None:
        fail("10 probe", "%s: no step with `id: probe` - the cluster-down skip is missing"
             % DEPLOY)
    else:
        probe_run = probe.get("run", "")
        if not re.search(r"^\s*set \+e\s*$", probe_run, re.MULTILINE):
            fail("10 probe",
                 "%s probe step does not start with `set +e`. GitHub runs every `run:` "
                 "block as `bash -e {0}`, and neither `set -u` nor `set -o pipefail` "
                 "clears errexit. Without `set +e` the first failing probe command "
                 "aborts the step and turns a torn-down cluster into a RED run." % DEPLOY)
        for line in join_continuations(probe_run):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Drop quoted spans so a command *named* inside an echo message is
            # not mistaken for an unguarded invocation of it.
            unquoted = re.sub(r"\"[^\"]*\"|'[^']*'", "", stripped)
            for cmd in ("aws eks describe-cluster", "kubectl get nodes"):
                if cmd not in unquoted:
                    continue
                guarded = (
                    re.match(r"^(el)?if\s+!?\s*", unquoted) is not None
                    or "||" in unquoted.split(cmd, 1)[1]
                )
                if not guarded:
                    fail("10 probe",
                         "%s probe step runs `%s` as a bare statement; it must sit in an "
                         "`if` condition or left of `||` so the step survives an absent "
                         "cluster even if `set +e` is later removed:\n        %s"
                         % (DEPLOY, cmd, stripped))

    # ---- 11. W4: detect-changes emits both output keys, old key gone ------
    _, changes = find_step(build, "detect-changes", lambda s: s.get("id") == "changes")
    if changes is None:
        fail("11 W4", "%s: no step with `id: changes` in detect-changes" % BUILD)
    else:
        run = changes.get("run", "")
        for key in ("services_json=", "services_list="):
            if key not in run:
                fail("11 W4", "%s detect-changes never writes `%s`" % (BUILD, key))
        stale = re.search(r'^\s*echo\s+["\']?services=', run, re.MULTILINE)
        if stale:
            fail("11 W4",
                 "%s detect-changes still writes the old output key `services=` "
                 "(%r). A branch writing it would leave services_json empty and the "
                 "build matrix would silently build nothing."
                 % (BUILD, stale.group(0).strip()))
        declared = ((build.get("jobs") or {}).get("detect-changes") or {}).get("outputs") or {}
        for key in ("services_json", "services_list"):
            if key not in declared:
                fail("11 W4", "%s: detect-changes does not declare output %r (declares: %s)"
                     % (BUILD, key, sorted(declared)))
        if "services" in declared:
            fail("11 W4", "%s: detect-changes still declares the old `services` output"
                 % BUILD)

    # ---- 12. S4: ECR guard present and before the image build -------------
    if "aws ecr describe-repositories" not in build_txt:
        fail("12 S4", "%s: no `aws ecr describe-repositories` guard; the first build of a "
                      "new service has no repository to push to" % BUILD)
    if "aws ecr create-repository" not in build_txt:
        fail("12 S4", "%s: no `aws ecr create-repository` fallback" % BUILD)
    ecr_i, _ = find_step(build, "build",
                         lambda s: "aws ecr describe-repositories" in str(s.get("run", "")))
    push_i, _ = find_step(build, "build",
                          lambda s: "docker/build-push-action" in str(s.get("uses", "")))
    if ecr_i < 0:
        fail("12 S4", "%s: the ECR guard is not a step of the `build` job" % BUILD)
    elif push_i < 0:
        fail("12 S4", "%s: no docker/build-push-action step in the `build` job" % BUILD)
    elif ecr_i >= push_i:
        fail("12 S4", "%s: the ECR guard is step %d but the image push is step %d; the "
                      "guard must run first" % (BUILD, ecr_i, push_i))

    # ---- 13. S5: rollout timeout and diagnostics --------------------------
    if "--timeout 10m" not in deploy_txt:
        fail("13 S5", "%s: expected `--timeout 10m` (charts run pre-deploy Alembic "
                      "migration Jobs; 5m is tight on a cold node)" % DEPLOY)
    if "--timeout 5m" in deploy_txt:
        fail("13 S5", "%s: still uses `--timeout 5m`" % DEPLOY)
    if "kubectl describe deployment" not in deploy_txt:
        fail("13 S5", "%s: a failed rollout must dump `kubectl describe deployment` "
                      "rather than a bare timeout" % DEPLOY)

    report()


def report():
    if FAILURES:
        print("workflow validation FAILED (%d problem(s)):\n" % len(FAILURES))
        for f in FAILURES:
            print("  FAIL " + f)
        print("")
        sys.exit(1)
    print("workflow validation PASSED (13 assertion groups)")
    print("NOTE: offline only - GitHub-side state (repository variables, secrets,")
    print("      environments, IAM trust policy, ECR repositories) is NOT checked.")
    sys.exit(0)


if __name__ == "__main__":
    main()
