// aca-dns.bicep — private DNS for an INTERNAL Container Apps environment.
// The zone name is the environment's default domain (known only after the environment exists),
// which is why this is a module: module *parameters* may be runtime values, resource *names* may not.

targetScope = 'resourceGroup'

@description('Environment default domain, e.g. <name>.<unique>.eastus2.azurecontainerapps.io')
param defaultDomain string

@description('Environment static (internal load balancer) IP.')
param staticIp string

@description('VNet resource id to link.')
param vnetId string

param tags object = {}

resource zone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: defaultDomain
  location: 'global'
  tags: tags
}

resource wildcard 'Microsoft.Network/privateDnsZones/A@2020-06-01' = {
  parent: zone
  name: '*'
  properties: {
    ttl: 300
    aRecords: [
      {
        ipv4Address: staticIp
      }
    ]
  }
}

resource apex 'Microsoft.Network/privateDnsZones/A@2020-06-01' = {
  parent: zone
  name: '@'
  properties: {
    ttl: 300
    aRecords: [
      {
        ipv4Address: staticIp
      }
    ]
  }
}

resource link 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: zone
  name: 'link-vnet-abw'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnetId
    }
  }
}

output zoneId string = zone.id
