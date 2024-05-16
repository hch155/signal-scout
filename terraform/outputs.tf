output "kube_config" {
  description = "Raw Kubernetes config to be used by kubectl and other compatible tools."
  value       = module.aks.kube_config_raw 
  sensitive   = true
}

output "cluster_node_resource_group" {
  description = "The auto-generated Resource Group which contains the resources for this Managed Kubernetes Cluster."
  value       = module.aks.node_resource_group
}

#output "kubelet_identity_object_id" {
#  value       = local.principal_id
#  description = "The Object ID of the kubelet identity used by the AKS cluster."
#}

