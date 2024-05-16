variable "resource_group_name" {
  description = "The name of the resource group"
  type        = string
}

variable "cluster_name" {
  description = "The name of the AKS cluster"
  type        = string
}

variable "kubernetes_version" {
  description = "The version of Kubernetes for the AKS cluster"
  type        = string
}

variable "client_secret" {
  description = "The client secret for the service principal"
  type        = string
}

variable "agent_count" {
  description = "The number of agent nodes for the default node pool"
  type        = number
}

variable "vm_size" {
  description = "The size of the virtual machines for the default node pool"
  type        = string
}

