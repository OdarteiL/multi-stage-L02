from diagrams import Diagram, Cluster, Edge
from diagrams.programming.language import NodeJS
from diagrams.onprem.container import Docker
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.vcs import Github
from diagrams.generic.storage import Storage

with Diagram("Multi-Stage Docker Build Optimization", filename="architecture", show=False, direction="LR"):

    with Cluster("Developer Workstation"):
        source = NodeJS("Node.js App\n(Source Code)")
        dockerignore = Storage(".dockerignore")

    with Cluster("Multi-Stage Dockerfile"):
        stage1 = Docker("Stage 1: Builder\n(node:20 full)\n~1.2GB")
        stage2 = Docker("Stage 2: Production\n(distroless/node)\n<120MB")
        stage1 >> Edge(label="COPY --from=builder\n(only dist/ artifacts)") >> stage2

    with Cluster("Local Tooling"):
        dive = Storage("dive\n(layer analysis)")
        trivy = Storage("trivy\n(vuln scan)")

    with Cluster("GitHub Actions CI"):
        ci = GithubActions("CI Pipeline")
        size_check = Storage("Size Regression\nCheck (<120MB)")
        vuln_scan = Storage("Trivy\nVulnerability Scan")

    registry = Storage("GHCR\n(GitHub Container Registry)")

    source >> Edge(label="docker build") >> stage1
    dockerignore >> Edge(style="dashed") >> stage1
    stage2 >> Edge(label="docker push") >> registry
    stage2 >> dive
    stage2 >> trivy

    Github("GitHub Repo") >> Edge(label="push / PR trigger") >> ci
    ci >> size_check
    ci >> vuln_scan
    ci >> Edge(label="on success") >> registry
