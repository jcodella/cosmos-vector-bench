using '../../infra/main.bicep'

param accountName = 'cosmos-tests'
param databaseName = 'testdb'
param containerName = 's6-quantizedFlat-500k'
param partitionKeyPath = '/docid'
param autoscaleMaxThroughput = 500000
param vectorPath = '/emb'
param vectorIndexType = 'quantizedFlat'
param vectorDimensions = 1536
param vectorDataType = 'float32'
param vectorDistanceFunction = 'cosine'
param defaultTtlSeconds = -1
