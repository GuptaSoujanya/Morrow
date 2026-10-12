# Full-Stack MERN + Deployment/Kubernetes — Interview Track

This track takes you from solid fundamentals to senior-level depth across the MERN stack (MongoDB, Express, React, Node.js) and the deployment layer (Docker, CI/CD, Kubernetes). It is one of four parallel tracks in the PrepForge course (the others cover System Design, DSA, and ML/GenAI).

Target reader: an engineer with working MERN experience who is preparing for **senior full-stack interviews** (roughly 5-12 years), where interviewers probe not just "how do you use X" but "why does X work this way, what breaks at scale, and how do you debug it in production."

## How to use this track

1. Read files in order (01 → 09). Each builds on the last.
2. Every concept file ends with **Practice Tasks** (do these — don't skip) and **Interview Questions** (use these to self-test).
3. Diagrams are in [Mermaid](https://mermaid.js.org/) syntax. They render natively on GitHub and in most markdown viewers (VS Code with the Markdown Preview Mermaid extension, Obsidian, etc.).
4. All code and YAML in this track is meant to be **complete and runnable as written** — not pseudocode. Copy it into a real project and adapt names/ports to your environment.

## File Index

| # | File | What you'll learn |
|---|------|--------------------|
| 01 | [01-nodejs-express.md](./01-nodejs-express.md) | Event loop internals, streams, clustering, Express middleware, error handling, REST API design, Node security (helmet, rate limiting, OWASP) |
| 02 | [02-mongodb.md](./02-mongodb.md) | Document modeling, embedding vs referencing, indexing strategy, aggregation pipeline, transactions, replication/sharding, Mongoose patterns |
| 03 | [03-react-advanced.md](./03-react-advanced.md) | Hooks deep dive, reconciliation/Fiber, performance (memo, useMemo, code splitting, virtualization), state management (Context vs Redux vs Zustand), SSR/Next.js overview, testing with RTL |
| 04 | [04-auth-and-api-security.md](./04-auth-and-api-security.md) | JWT vs sessions, refresh token rotation, OAuth2 flows, RBAC, CORS, CSRF/XSS prevention — with sequence diagrams |
| 05 | [05-fullstack-project-architecture.md](./05-fullstack-project-architecture.md) | Production-grade MERN reference architecture: folder structure, env config, validation, logging, Redis caching, WebSockets |
| 06 | [06-docker-cicd.md](./06-docker-cicd.md) | Multi-stage Dockerfiles for Node/React, docker-compose for full MERN stack, complete GitHub Actions CI/CD pipeline |
| 07 | [07-kubernetes.md](./07-kubernetes.md) | K8s architecture, Pods/Deployments/Services/Ingress, ConfigMaps/Secrets, probes, HPA, resource limits, rolling updates, full manifests to deploy MERN on K8s, Helm basics |
| 08 | [08-production-operations.md](./08-production-operations.md) | Monitoring (Prometheus/Grafana), logging, scaling strategies, zero-downtime deploys, debugging pods, cost basics |
| 09 | [09-interview-questions.md](./09-interview-questions.md) | 60+ interview Q&A at senior depth, organized by topic, plus scenario-based questions |

## Suggested study plan (2-3 weeks)

- **Week 1**: Files 01-04 (Node, MongoDB, React, Auth). These are the "application layer" fundamentals interviewers probe hardest.
- **Week 2**: Files 05-07 (Architecture, Docker/CI-CD, Kubernetes). This is where senior candidates separate themselves — most mid-level engineers stop at "it works on my laptop."
- **Week 3**: File 08 (Operations) + File 09 (mock interview using the Q&A bank). Do the Practice Tasks you skipped.

## Prerequisites assumed

- You've built at least one MERN CRUD app before.
- Basic Linux command line comfort.
- Basic Git.

You do **not** need prior Docker/Kubernetes experience — those are taught from first principles in files 06-07.

Good luck. Treat the Practice Tasks as mandatory, not optional — interviewers can tell who has only read about these concepts versus who has actually broken and fixed them.
