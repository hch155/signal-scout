terraform {
  required_version = ">= 1.3" # Terraform version is at least 1.3
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.103.1" # latest patch version
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
  }
}
