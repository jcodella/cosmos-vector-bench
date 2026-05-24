using '../../infra/main.bicep'

param accountName = '<existing-account-name>'
param databaseName = 'testdb'
param containerName = 'benchmark-openai-c5-diskann'
param partitionKeyPath = '/docid'
param autoscaleMaxThroughput = 8000
param vectorPath = '/emb'
param vectorIndexType = 'diskANN'
param vectorDimensions = 1536
param vectorDataType = 'float32'
param vectorDistanceFunction = 'cosine'
param defaultTtlSeconds = 86400