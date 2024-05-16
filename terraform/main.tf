# Define random ID for prefix
resource "random_id" "prefix" {
  byte_length = 8
}

# Data block for existing resource group
data "azurerm_resource_group" "aks" {
  name = var.resource_group_name
}

# Data block for client configuration
data "azurerm_client_config" "current" {}

# Data block for existing Azure Container Registry
data "azurerm_container_registry" "acr" {
  name                = "signalscoutaks"
  resource_group_name = data.azurerm_resource_group.aks.name
}

# Local variables
locals {
  acr_resource_id = data.azurerm_container_registry.acr.id
}

# AKS module
module "aks" {
  source  = "Azure/aks/azurerm"
  version = "8.0.0"

  resource_group_name                  = data.azurerm_resource_group.aks.name
  location                             = data.azurerm_resource_group.aks.location
  cluster_name                         = var.cluster_name
  kubernetes_version                   = var.kubernetes_version
  client_secret                        = var.client_secret
  prefix                               = "signal-scout-AKS-cluster-dns-${random_id.prefix.hex}"
  role_based_access_control_enabled    = true
  rbac_aad_managed 		       = true	

  node_pools = {
    default = {
      name       = "default"
      node_count = var.agent_count
      vm_size    = var.vm_size
    }
  }

  tags = {
    Environment = "PRODUCTION"
  }
}
