# Execution Shapes Reference

This reference covers the three ways CI pipelines invoke HawkScan, per-provider quick-reference recipes for setting the API key secret, and provider-specific gotchas.

## The Three Tiers

| Tier | Mechanism | Pros | Cons | When to use |
|---|---|---|---|---|
| **1. Native action** | `stackhawk/hawkscan-action@vX.Y.Z` | Richest input surface (SARIF upload, PR comments, Code Scanning, `commitShaCheck`, multi-file overlays). One-line invocation. Network plumbing for localhost handled automatically. | GitHub Actions only. | GitHub Actions runners. |
| **2. Docker image** | `docker run stackhawk/hawkscan:latest` | Works in any runner with Docker. Same binary as production scans. `:latest` tracks the newest stable scanner. | Networking-to-localhost requires `--network host` (Linux) or `host.docker.internal` (Mac/Windows runners). DinD setup on GitLab. | Anywhere Docker is available — GitLab, Jenkins, CircleCI, Azure, Bitbucket, Buildkite, AWS CodeBuild. |
| **3. CLI download** | `curl -Lo hawk.zip https://download.stackhawk.com/hawk/cli/hawk-${VERSION}.zip` | No Docker required. Lightest footprint. | Java 17+ must be present (separate install for Linux runners). Slower bootstrap than image pull on warm cache. | Bare shell runners with no Docker — some Travis configs, restricted Spinnaker stages, locked-down corporate runners. |

## Versioning Strategy

**Use `:latest` for the StackHawk scanner image.** HawkScan is a security scanner — the newest stable build carries the latest checks and detections, so CI should track it rather than freeze on an older release. StackHawk publishes `stackhawk/hawkscan:latest` as the current stable release.

| Mechanism | Recommended | Notes |
|---|---|---|
| Scanner image | `stackhawk/hawkscan:latest` | Newest stable scanner — best detection coverage. |
| Native action | `stackhawk/hawkscan-action@v2` | Major pin auto-receives the newest action within v2. |
| CLI download | resolve via `curl -s https://api.stackhawk.com/hawkscan/version` | Downloads the current stable CLI. |

**If your org mandates fully reproducible builds**, pin an explicit version instead — `stackhawk/hawkscan:<X.Y.Z>` (resolve the current via the version endpoint), `stackhawk/hawkscan-action@vX.Y.Z`, or an image digest (`stackhawk/hawkscan@sha256:...`, bumped via Dependabot/Renovate). The tradeoff is that a frozen scanner won't pick up newly-added checks until you bump it.

## Per-Provider Quick Reference

### GitHub Actions

**Secret:** `gh secret set HAWK_API_KEY` (interactive paste), or **Settings → Secrets and variables → Actions → New repository secret**.

**Recommended execution shape:** native action (`stackhawk/hawkscan-action@v2.5.0`).

**Minimal job block:**

```yaml
jobs:
  hawkscan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Start app
        run: docker compose up -d
      - name: Run HawkScan
        uses: stackhawk/hawkscan-action@v2.5.0
        env:
          COMMIT_SHA: ${{ github.sha }}
          BRANCH_NAME: ${{ github.head_ref || github.ref_name }}
        with:
          apiKey: ${{ secrets.HAWK_API_KEY }}
      - name: Upload scan report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: hawkscan-report
          path: hawkscan-report/
```

**Gotchas:** none specific to the action — it handles localhost networking, runs the scan synchronously, and propagates the exit code.

### GitLab CI/CD

**Secret:** **mandatory key split** — GitLab's variable masker treats the `.` separators in `hawk.<id>.<secret>` as glob anchors and refuses to mask the value, breaking masking. Split the API key into two protected/masked variables:

```bash
# Given HAWK_API_KEY="hawk.aaaaaaaa.bbbbbbbb"
glab variable set HAWK_API_ID aaaaaaaa --masked --protected
glab variable set HAWK_API_SECRET bbbbbbbb --masked --protected
# Reassemble in the job: API_KEY="hawk.${HAWK_API_ID}.${HAWK_API_SECRET}"
```

**Recommended execution shape:** Docker image via DinD.

**Minimal job block:**

```yaml
hawkscan:
  image: docker:24
  services:
    - docker:24-dind
  variables:
    HAWK_VERSION: "latest"
  script:
    - docker pull stackhawk/hawkscan:${HAWK_VERSION}
    - |
      docker run --rm \
        -v "$(pwd):/hawk:rw" \
        -e API_KEY="hawk.${HAWK_API_ID}.${HAWK_API_SECRET}" \
        -e NO_COLOR=true \
        -e COMMIT_SHA="${CI_COMMIT_SHA}" \
        -e BRANCH_NAME="${CI_COMMIT_REF_NAME}" \
        --network host \
        stackhawk/hawkscan:${HAWK_VERSION}
  artifacts:
    when: always
    paths:
      - hawkscan/
```

**Gotchas:** GitLab runners with the Docker executor need `privileged = true` in `config.toml`, plus the `/var/run/docker.sock` and `/builds:/builds` volume mounts.

### Jenkins

**Secret:** **Manage Jenkins → Credentials → Add Credentials → "Secret text"**, ID `HAWK_API_KEY`. Jenkins doesn't have a first-class CLI for this; UI only.

**Recommended execution shape:** Docker image (Jenkins host needs Docker daemon access).

**Declarative pipeline:**

```groovy
pipeline {
  agent any
  environment {
    HAWK_API_KEY = credentials('HAWK_API_KEY')
    HAWK_VERSION = 'latest'
    COMMIT_SHA   = "${env.GIT_COMMIT}"
    BRANCH_NAME  = "${env.BRANCH_NAME}"
  }
  stages {
    stage('Start app') {
      steps { sh 'docker compose up -d' }
    }
    stage('Run HawkScan') {
      steps {
        sh '''
          docker pull stackhawk/hawkscan:${HAWK_VERSION}
          docker run --rm \\
            -v "$(pwd):/hawk:rw" \\
            -e API_KEY=$HAWK_API_KEY \\
            -e COMMIT_SHA -e BRANCH_NAME \\
            --network host \\
            stackhawk/hawkscan:${HAWK_VERSION}
        '''
      }
      post {
        always { archiveArtifacts artifacts: 'hawkscan/**', allowEmptyArchive: true }
      }
    }
  }
}
```

**Gotchas:** the `jenkins` user must be in the `docker` group on the controller/agent (`sudo usermod -aG docker jenkins && sudo systemctl restart jenkins`). Otherwise the Docker invocation fails with "permission denied while trying to connect to the Docker daemon socket".

### CircleCI

**Secret:** `circleci context store-secret <context-name> HAWK_API_KEY` (org-scoped Contexts via the CircleCI CLI), or **Project Settings → Environment Variables** (UI). For project-scoped secrets the CLI form is `circleci project secret create <vcs-type> <org> <project>`.

**Recommended execution shape:** Docker image (CircleCI natively runs jobs in containers).

**Minimal job block:**

```yaml
jobs:
  hawkscan:
    machine:
      image: ubuntu-2404:current
    steps:
      - checkout
      - run:
          name: Start app
          command: docker compose up -d
      - run:
          name: Run HawkScan
          command: |
            docker pull stackhawk/hawkscan:latest
            docker run --rm \
              -v "$(pwd):/hawk:rw" \
              -e API_KEY=$HAWK_API_KEY \
              -e COMMIT_SHA=$CIRCLE_SHA1 \
              -e BRANCH_NAME=$CIRCLE_BRANCH \
              --network host \
              stackhawk/hawkscan:latest
      - store_artifacts:
          path: hawkscan/
```

**Gotchas:** the `machine:` executor runs the app and scanner on the same host, so `--network host` reaches the app. If you instead use the `docker:` executor with `setup_remote_docker`, the app and scanner run on a separate Docker host and `localhost` won't bridge between them — start the app in that same remote-Docker context and target its published port, or stay on the `machine:` executor as shown above.

### Azure Pipelines

**Secret:** `az pipelines variable create --name HAWK_API_KEY --secret true` or add via **Pipeline → Edit → Variables**.

**Recommended execution shape:** Docker image, or the StackHawk Marketplace Extension for guided installation.

**Minimal job block (Docker image):**

```yaml
jobs:
  - job: hawkscan
    pool:
      vmImage: 'ubuntu-latest'
    variables:
      HAWK_VERSION: 'latest'
    steps:
      - checkout: self
      - script: docker compose up -d
        displayName: 'Start app'
      - script: |
          docker pull stackhawk/hawkscan:$(HAWK_VERSION)
          docker run --rm \
            -v "$(pwd):/hawk:rw" \
            -e API_KEY=$HAWK_API_KEY \
            -e COMMIT_SHA=$(Build.SourceVersion) \
            -e BRANCH_NAME=$(Build.SourceBranchName) \
            --network host \
            stackhawk/hawkscan:$(HAWK_VERSION)
        displayName: 'Run HawkScan'
        env:
          HAWK_API_KEY: $(HAWK_API_KEY)
      - task: PublishBuildArtifacts@1
        condition: always()
        inputs:
          PathtoPublish: '$(System.DefaultWorkingDirectory)/hawkscan'
          ArtifactName: 'hawkscan-report'
```

**Alternative:** the [StackHawk Marketplace Extension](https://marketplace.visualstudio.com/items?itemName=stackhawk.stackhawk-hawkscan-azure-extension) wraps the same Docker invocation behind a GUI task. Use it if your team prefers task-library installs.

### Bitbucket Pipelines

**Secret:** **Repository settings → Repository variables → Add variable**, with the "Secured" checkbox.

**Recommended execution shape:** Docker image.

**Minimal pipeline block:**

```yaml
pipelines:
  default:
    - step:
        name: HawkScan
        image: atlassian/default-image:4
        services: [docker]
        script:
          - docker compose up -d
          - timeout 60 bash -c 'until curl -fsS http://localhost:8080/health; do sleep 2; done'
          - >
            docker run --rm
            -v "$(pwd):/hawk:rw"
            -e API_KEY=$HAWK_API_KEY
            -e COMMIT_SHA=$BITBUCKET_COMMIT
            -e BRANCH_NAME=$BITBUCKET_BRANCH
            --network host
            stackhawk/hawkscan:latest
        artifacts:
          - hawkscan/**
```

**Gotchas:** the step `image:` must include the Docker CLI (`atlassian/default-image:4` does) — the `stackhawk/hawkscan` image is a JVM scanner with no Docker client, so it can't be the step image that runs `docker compose`. Invoke HawkScan as a `docker run` container instead. Bitbucket's `services: [docker]` adds a 1GB memory allocation by default — bump to `step.size: 2x` if scans run out of memory.

### Buildkite

**Secret:** Buildkite has no built-in secret store — wire to an external secrets manager (AWS Secrets Manager + the `secrets` agent hook is the documented pattern).

**Recommended execution shape:** Docker image via the `docker#v5.x.x` plugin.

```yaml
steps:
  - label: ":lock: HawkScan"
    command: hawk scan
    plugins:
      - docker#v5.10.0:
          image: stackhawk/hawkscan:latest
          environment:
            - API_KEY
            - COMMIT_SHA=$BUILDKITE_COMMIT
            - BRANCH_NAME=$BUILDKITE_BRANCH
          volumes:
            - .:/hawk
```

### Travis CI

**Secret:** `travis encrypt HAWK_API_KEY=hawk.aaaa.bbbb --add` (Travis CLI).

**Recommended execution shape:** Docker image (Travis runners support Docker).

```yaml
services: [docker]
script:
  - docker compose up -d
  - |
    docker run --rm \
      -v "$(pwd):/hawk:rw" \
      -e API_KEY="$HAWK_API_KEY" \
      -e COMMIT_SHA="$TRAVIS_COMMIT" \
      -e BRANCH_NAME="$TRAVIS_BRANCH" \
      --network host \
      stackhawk/hawkscan:latest
```

### AWS CodeBuild

**Secret:** store in AWS Secrets Manager, reference via the `secrets-manager:` syntax in `buildspec.yml`. CodeBuild also supports `parameter-store:` for SSM.

**Recommended execution shape:** Docker image.

```yaml
version: 0.2
env:
  secrets-manager:
    HAWK_API_KEY: "stackhawk/hawk-api-key:HAWK_API_KEY"
phases:
  build:
    commands:
      - docker compose up -d
      - |
        docker run --rm \
          -v "$(pwd):/hawk:rw" \
          -e API_KEY=$HAWK_API_KEY \
          -e COMMIT_SHA=$CODEBUILD_RESOLVED_SOURCE_VERSION \
          -e BRANCH_NAME=$CODEBUILD_WEBHOOK_HEAD_REF \
          --network host \
          stackhawk/hawkscan:latest
artifacts:
  files:
    - hawkscan/**/*
```

## Long-Tail Providers

For Bamboo, Concourse, Harness, Spinnaker, and other providers not listed above, defer to the per-provider canonical guides at [docs.stackhawk.com/integrations/ci-cd/](https://docs.stackhawk.com/integrations/ci-cd/). The Docker-image pattern from the table above adapts cleanly to all of them — only the secret-store wiring and artifact-publishing mechanism differ.

## Code Scanning / SARIF Upload (GitHub Actions only)

The `stackhawk/hawkscan-action` supports SARIF upload to GitHub Code Scanning via `codeScanningAlerts: true` + the `githubToken` input. Opt-in only; not enabled by default. See the action's [README](https://github.com/stackhawk/hawkscan-action) for details. This skill does not add the input automatically — the user can enable it post-write.
