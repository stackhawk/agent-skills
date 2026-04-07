# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | Yes                |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please email **vdp@stackhawk.com** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact

We will acknowledge receipt within 48 hours and provide a timeline for a fix.

## Scope

This repository contains agent skill definitions (Markdown files and JSON manifests). It does not contain executable application code. Security concerns most likely relate to:

- Skill instructions that could lead to unsafe agent behavior
- Manifest configurations that could be exploited during plugin installation
- Supply chain concerns in CI/CD workflows
