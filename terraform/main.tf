terraform {
  required_version = ">= 1.5.0"
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0.0"
    }
  }
}

provider "docker" {
  host = "unix:///var/run/docker.sock"
}

# Input variables for configuring WLCG site sizing
variable "cluster_name" {
  type        = string
  default     = "cern-wlcg-sim"
  description = "Base name for the cluster nodes"
}

variable "worker_count" {
  type        = number
  default     = 2
  description = "Number of simulated grid compute nodes to provision"
}

variable "django_port" {
  type        = number
  default     = 8000
  description = "External port for the Django control plane dashboard"
}

# Networks
resource "docker_network" "grid_network" {
  name = "${var.cluster_name}-net"
}

# Image Definitions
resource "docker_image" "postgres" {
  name         = "postgres:15-alpine"
  keep_locally = true
}

resource "docker_image" "redis" {
  name         = "redis:7-alpine"
  keep_locally = true
}

# Core Services
resource "docker_container" "db" {
  name  = "grid_db"
  image = docker_image.postgres.image_id
  networks_advanced {
    name = docker_network.grid_network.name
  }
  env = [
    "POSTGRES_DB=grid_sentinel",
    "POSTGRES_USER=postgres",
    "POSTGRES_PASSWORD=postgrespassword"
  ]
  ports {
    internal = 5432
    external = 5432
  }
}

resource "docker_container" "redis_cache" {
  name  = "grid_redis"
  image = docker_image.redis.image_id
  networks_advanced {
    name = docker_network.grid_network.name
  }
}

# Worker Node Provisioning Loop
resource "docker_container" "workers" {
  count = var.worker_count
  name  = "${var.cluster_name}-worker-${format("%02d", count.index + 1)}"
  image = "python:3.11-slim"
  networks_advanced {
    name = docker_network.grid_network.name
  }
  
  entrypoint = ["python", "-c", "import time; print('Simulating worker agent...'); time.sleep(3600)"]
  
  env = [
    "CONTROL_PLANE_URL=http://django:8000",
    "NODE_HOSTNAME=${var.cluster_name}-worker-${format("%02d", count.index + 1)}"
  ]

  labels {
    label = "cern-grid-component"
    value = "worker"
  }
}

# Output node metadata for administrative classification
output "control_plane_url" {
  value       = "http://localhost:${var.django_port}"
  description = "The access URL for the SciOps Sentinel Web Dashboard"
}

output "provisioned_workers" {
  value = [
    for w in docker_container.workers : {
      name = w.name
      ip   = w.network_data[0].ip_address
    }
  ]
  description = "List of provisioned worker nodes and their network designations"
}
