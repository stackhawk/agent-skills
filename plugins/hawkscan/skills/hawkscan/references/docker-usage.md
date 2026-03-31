# HawkScan Docker Usage Reference

Use Docker when the `hawk` CLI isn't installed or in CI environments with Docker support.

## Standard Run

```bash
# Mounts current dir as /hawk
docker run --rm \
  -v $(pwd):/hawk:rw \
  -e API_KEY=${HAWK_API_KEY} \
  -t stackhawk/hawkscan:latest
```

## Scan Localhost (App on Host Network)

```bash
docker run --rm \
  -v $(pwd):/hawk:rw \
  --network host \
  -e API_KEY=${HAWK_API_KEY} \
  -t stackhawk/hawkscan:latest
```

## Custom Config File

```bash
docker run --rm \
  -v $(pwd):/hawk:rw \
  -e API_KEY=${HAWK_API_KEY} \
  -t stackhawk/hawkscan:latest stackhawk-ci.yml
```

## Merged Configs

Later files take precedence:

```bash
docker run --rm \
  -v $(pwd):/hawk:rw \
  -e API_KEY=${HAWK_API_KEY} \
  -t stackhawk/hawkscan:latest base.yml ci-override.yml
```

## JSON Output (Agentic Use)

**Note:** `--json-output` requires at least HawkScan Dev Release v5.3.41.

```bash
docker run --rm \
  -v $(pwd):/hawk:rw \
  -e API_KEY=${HAWK_API_KEY} \
  -t stackhawk/hawkscan:latest --json-output
```

## Networking Notes

Docker cannot reach `localhost` on the host by default:
- **Linux:** Use `--network host`
- **Mac/Windows:** Use `host.docker.internal` as the hostname in `stackhawk.yml`
