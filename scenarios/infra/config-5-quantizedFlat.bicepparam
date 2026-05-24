using '../../infra/main.bicep'

param accountName = '<existing-account-name>'
param databaseName = 'testdb'
param containerName = 'benchmark-openai-c5-quantizedflat'
param partitionKeyPath = '/docid'
param autoscaleMaxThroughput = 4000
param vectorPath = '/emb'
param vectorIndexType = 'quantizedFlat'
param vectorDimensions = 1536
param vectorDataType = 'float32'
param vectorDistanceFunction = 'cosine'
param defaultTtlSeconds = 86400