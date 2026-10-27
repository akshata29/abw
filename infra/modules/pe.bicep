// pe.bicep — private endpoint + private DNS zone group for one Azure resource.
// Zones are created/linked in 01-network.bicep (same resource group).

targetScope = 'resourceGroup'

param name string
param location string = resourceGroup().location
param subnetId string
param privateLinkResourceId string

@description('Sub-resource group id, e.g. blob, Sql, searchService, vault, sites, Gateway.')
param groupId string

@description('Private DNS zone FQDN in this resource group, e.g. privatelink.blob.core.windows.net')
param zoneName string

param tags object = {}

resource pe 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: name
        properties: {
          privateLinkServiceId: privateLinkResourceId
          groupIds: [
            groupId
          ]
        }
      }
    ]
  }
}

resource zoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'zone'
        properties: {
          privateDnsZoneId: resourceId('Microsoft.Network/privateDnsZones', zoneName)
        }
      }
    ]
  }
}

output id string = pe.id
