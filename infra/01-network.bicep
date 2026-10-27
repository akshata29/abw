// 01-network.bicep — Agents Behind the Wall: network foundation.
//
// VNet + 4 purpose-built subnets, a shared NAT gateway for the two subnets that must
// reach Entra/Azure Monitor/public vendor APIs, an NSG for the APIM integration subnet,
// and EVERY private DNS zone the platform needs (created once, linked once).
//
// Design notes (see DESIGN.md §2/§9):
//   * snet-agent  : delegated Microsoft.App/environments, Foundry Agent Service injection.
//                   NO NAT, NO default outbound -> the agent runtime has no path to the internet.
//   * snet-pe     : private endpoints for Foundry, Storage, Cosmos, Search, APIM, AMPLS, Key Vault.
//   * snet-mcp    : delegated Microsoft.App/environments, internal Container Apps environment
//                   (the private MCP + all MCP servers). NAT for Entra JWKS / OBO / ingestion.
//   * snet-apim   : delegated Microsoft.Web/serverFarms, APIM Standard v2 outbound integration.
//
// All DNS zones live in THIS resource group and are linked to the VNet here, so the vendored
// Foundry template (infra/foundry) is told to *reference* them instead of creating its own.

targetScope = 'resourceGroup'

@description('Azure region.')
param location string = resourceGroup().location

@description('Virtual network name (CAF: vnet-<workload>-<env>-<region>-<instance>).')
param vnetName string

@description('NAT gateway name.')
param natGatewayName string

@description('NSG name for the APIM integration subnet.')
param apimNsgName string

@description('Resource tags.')
param tags object = {}

@description('VNet address space.')
param addressPrefix string = '10.42.0.0/16'

param agentSubnetPrefix string = '10.42.0.0/24'
param peSubnetPrefix string = '10.42.1.0/24'
param mcpSubnetPrefix string = '10.42.2.0/24'
param apimSubnetPrefix string = '10.42.3.0/26'

var storageSuffix = environment().suffixes.storage

// Every zone any later stage needs. The vendored Foundry template consumes the first 13 (it
// references them as "existing"); APIM uses privatelink.azure-api.net; the Container Apps
// environment zone is created in 03-platform once the environment's default domain is known.
var dnsZoneNames = [
  'privatelink.services.ai.azure.com'
  'privatelink.openai.azure.com'
  'privatelink.cognitiveservices.azure.com'
  'privatelink.search.windows.net'
  'privatelink.blob.${storageSuffix}'
  'privatelink.documents.azure.com'
  'privatelink.fabric.microsoft.com'
  'privatelink.azurecr.io'
  'privatelink.vaultcore.azure.net'
  'privatelink.monitor.azure.com'
  'privatelink.oms.opinsights.azure.com'
  'privatelink.ods.opinsights.azure.com'
  'privatelink.agentsvc.azure-automation.net'
  'privatelink.azure-api.net'
]

resource apimNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: apimNsgName
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        // Required by APIM v2 VNet integration: Key Vault is a platform dependency.
        name: 'allow-out-keyvault-443'
        properties: {
          priority: 100
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'AzureKeyVault'
          destinationPortRange: '443'
        }
      }
      {
        // Gateway -> private MCP / Foundry private endpoints inside the VNet.
        name: 'allow-out-vnet-443'
        properties: {
          priority: 110
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '443'
        }
      }
      {
        // Gateway -> public vendor MCP mock and Entra/Monitor endpoints (via NAT).
        name: 'allow-out-internet-443'
        properties: {
          priority: 120
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Internet'
          destinationPortRange: '443'
        }
      }
    ]
  }
}

resource natPip 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-${natGatewayName}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource natGateway 'Microsoft.Network/natGateways@2024-05-01' = {
  name: natGatewayName
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    idleTimeoutInMinutes: 10
    publicIpAddresses: [
      {
        id: natPip.id
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        addressPrefix
      ]
    }
    subnets: [
      {
        name: 'snet-agent'
        properties: {
          addressPrefix: agentSubnetPrefix
          defaultOutboundAccess: false
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'snet-pe'
        properties: {
          addressPrefix: peSubnetPrefix
          defaultOutboundAccess: false
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'snet-mcp'
        properties: {
          addressPrefix: mcpSubnetPrefix
          natGateway: {
            id: natGateway.id
          }
          delegations: [
            {
              name: 'Microsoft.App.environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'snet-apim'
        properties: {
          addressPrefix: apimSubnetPrefix
          natGateway: {
            id: natGateway.id
          }
          networkSecurityGroup: {
            id: apimNsg.id
          }
          delegations: [
            {
              name: 'Microsoft.Web.serverFarms'
              properties: {
                serviceName: 'Microsoft.Web/serverFarms'
              }
            }
          ]
        }
      }
    ]
  }
}

resource zones 'Microsoft.Network/privateDnsZones@2020-06-01' = [for zone in dnsZoneNames: {
  name: zone
  location: 'global'
  tags: tags
}]

resource zoneLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (zone, i) in dnsZoneNames: {
  parent: zones[i]
  name: '${replace(zone, '.', '-')}-link'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}]

output vnetId string = vnet.id
output vnetName string = vnet.name
output agentSubnetId string = '${vnet.id}/subnets/snet-agent'
output peSubnetId string = '${vnet.id}/subnets/snet-pe'
output mcpSubnetId string = '${vnet.id}/subnets/snet-mcp'
output apimSubnetId string = '${vnet.id}/subnets/snet-apim'
output natPublicIp string = natPip.properties.ipAddress
output dnsZoneNames array = dnsZoneNames
