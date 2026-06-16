using System.Text.Json.Nodes;
using System.Threading.Channels;
using Microsoft.Azure.Cosmos;

namespace CosmosVectorBench;

/// <summary>
/// Orchestrates a benchmark run: opens the Cosmos client and container, launches logical client workers,
/// drives the live aggregate reporter, and prints/writes the final aggregated metrics.
/// </summary>
public sealed class Benchmark
{
    private readonly BenchmarkConfig _config;
    private readonly MetricsReporter _reporter;

    public Benchmark(BenchmarkConfig config)
    {
        _config = config;
        _reporter = new MetricsReporter(config);
    }

    public async Task<int> RunAsync()
    {
        using CosmosClient client = CosmosClientFactory.Create(_config);
        Container container = client.GetContainer(_config.Database, _config.Container);
        var writer = new CosmosWriter(_config, container);

        return _config.DataType == "file"
            ? await RunFileModeAsync(writer).ConfigureAwait(false)
            : await RunFakeModeAsync(writer).ConfigureAwait(false);
    }

    private async Task<int> RunFakeModeAsync(CosmosWriter writer)
    {
        string text = new string('x', _config.PayloadBytes);
        var slices = Worker.WorkerSlices(_config.EffectiveTotalDocs, _config.ClientProcesses);
        var metrics = new WorkerMetrics[_config.ClientProcesses];
        var workers = new Task[_config.ClientProcesses];
        using var cts = new CancellationTokenSource();
        double totalStartedAt = Clock.Now;

        for (int i = 0; i < _config.ClientProcesses; i++)
        {
            (int index, int start, int count) = slices[i];
            metrics[i] = new WorkerMetrics(_config);
            IAsyncEnumerable<List<JsonObject>> batches = Worker.ToAsync(
                DataSource.GenerateBulks(start, start + count, _config.BulkSize, text, _config.FakeDataVectorDim), cts.Token);
            workers[index] = Worker.RunAsync(writer, batches, metrics[index], _config.MaxInFlight, cts.Token);
        }

        return await DriveAsync(metrics, workers, _config.EffectiveTotalDocs, totalStartedAt, cts, producer: null).ConfigureAwait(false);
    }

    private Task<int> RunFileModeAsync(CosmosWriter writer)
        => _config.UseStreamWriter ? RunFileStreamModeAsync(writer) : RunFileObjectModeAsync(writer);

    private async Task<int> RunFileObjectModeAsync(CosmosWriter writer)
    {
        long queueMaxDocs = (long)_config.ClientProcesses * _config.BulkSize * _config.DocQueueMultiplier;
        int queueMaxSize = (int)Math.Max(1, (queueMaxDocs + _config.ReadBatchSize - 1) / _config.ReadBatchSize);
        var channel = Channel.CreateBounded<List<JsonObject>>(new BoundedChannelOptions(queueMaxSize)
        {
            SingleWriter = true,
            SingleReader = false,
            FullMode = BoundedChannelFullMode.Wait,
        });

        var metrics = new WorkerMetrics[_config.ClientProcesses];
        var workers = new Task[_config.ClientProcesses];
        using var cts = new CancellationTokenSource();
        double totalStartedAt = Clock.Now;

        for (int i = 0; i < _config.ClientProcesses; i++)
        {
            metrics[i] = new WorkerMetrics(_config);
            IAsyncEnumerable<List<JsonObject>> batches = Worker.QueueBulks(channel.Reader, _config.BulkSize, cts.Token);
            workers[i] = Worker.RunAsync(writer, batches, metrics[i], _config.MaxInFlight, cts.Token);
        }

        Task<long> producer = Task.Run(() => Produce(channel.Writer, cts.Token), cts.Token);

        long? liveTotalDocs = _config.MaxTotalDocs;
        return await DriveAsync(metrics, workers, liveTotalDocs, totalStartedAt, cts, producer).ConfigureAwait(false);
    }

    private async Task<int> RunFileStreamModeAsync(CosmosWriter writer)
    {
        long queueMaxDocs = (long)_config.ClientProcesses * _config.BulkSize * _config.DocQueueMultiplier;
        int queueMaxSize = (int)Math.Max(1, (queueMaxDocs + _config.ReadBatchSize - 1) / _config.ReadBatchSize);
        var channel = Channel.CreateBounded<List<byte[]>>(new BoundedChannelOptions(queueMaxSize)
        {
            SingleWriter = true,
            SingleReader = false,
            FullMode = BoundedChannelFullMode.Wait,
        });

        var metrics = new WorkerMetrics[_config.ClientProcesses];
        var workers = new Task[_config.ClientProcesses];
        using var cts = new CancellationTokenSource();
        double totalStartedAt = Clock.Now;

        for (int i = 0; i < _config.ClientProcesses; i++)
        {
            metrics[i] = new WorkerMetrics(_config);
            IAsyncEnumerable<List<byte[]>> batches = Worker.QueueBulks(channel.Reader, _config.BulkSize, cts.Token);
            workers[i] = Worker.RunRawAsync(writer, batches, metrics[i], _config.MaxInFlight, cts.Token);
        }

        Task<long> producer = Task.Run(() => ProduceRaw(channel.Writer, cts.Token), cts.Token);

        long? liveTotalDocs = _config.MaxTotalDocs;
        return await DriveAsync(metrics, workers, liveTotalDocs, totalStartedAt, cts, producer).ConfigureAwait(false);
    }

    private long Produce(ChannelWriter<List<JsonObject>> channelWriter, CancellationToken cancellationToken)
    {
        long docsRead = 0;
        Exception? failure = null;
        try
        {
            var pending = new List<JsonObject>(_config.ReadBatchSize);

            void Flush()
            {
                if (pending.Count == 0)
                {
                    return;
                }

                var batch = new List<JsonObject>(pending);
                pending.Clear();
                // Bounded channel: block synchronously via the async write awaited on this producer task.
                channelWriter.WriteAsync(batch, cancellationToken).AsTask().GetAwaiter().GetResult();
            }

            docsRead = DataSource.StreamJsonDocs(_config, _config.MaxTotalDocs, doc =>
            {
                pending.Add(doc);
                if (pending.Count >= _config.ReadBatchSize)
                {
                    Flush();
                }
            }, cancellationToken);

            Flush();
        }
        catch (Exception ex)
        {
            failure = ex;
        }
        finally
        {
            channelWriter.TryComplete(failure);
        }

        return docsRead;
    }

    private long ProduceRaw(ChannelWriter<List<byte[]>> channelWriter, CancellationToken cancellationToken)
    {
        long docsRead = 0;
        Exception? failure = null;
        try
        {
            var pending = new List<byte[]>(_config.ReadBatchSize);

            void Flush()
            {
                if (pending.Count == 0)
                {
                    return;
                }

                var batch = new List<byte[]>(pending);
                pending.Clear();
                // Bounded channel: block synchronously via the async write awaited on this producer task.
                channelWriter.WriteAsync(batch, cancellationToken).AsTask().GetAwaiter().GetResult();
            }

            docsRead = DataSource.StreamRawJsonDocs(_config, _config.MaxTotalDocs, raw =>
            {
                pending.Add(raw);
                if (pending.Count >= _config.ReadBatchSize)
                {
                    Flush();
                }
            }, cancellationToken);

            Flush();
        }
        catch (Exception ex)
        {
            failure = ex;
        }
        finally
        {
            channelWriter.TryComplete(failure);
        }

        return docsRead;
    }

    private async Task<int> DriveAsync(
        WorkerMetrics[] metrics,
        Task[] workers,
        long? liveTotalDocs,
        double totalStartedAt,
        CancellationTokenSource cts,
        Task<long>? producer)
    {
        var allWorkers = Task.WhenAll(workers);
        var aggregateThroughputSamples = new List<double>();

        try
        {
            while (true)
            {
                foreach (WorkerMetrics worker in metrics)
                {
                    worker.RecordThroughputSample();
                }

                var snapshots = metrics.Select(m => m.LiveSnapshot()).ToList();
                string line = _reporter.BuildAggregateLine(snapshots, liveTotalDocs, _config.ClientProcesses, aggregateThroughputSamples);
                _reporter.PrintLiveLine(line);

                Task finished = await Task.WhenAny(allWorkers, Task.Delay(TimeSpan.FromSeconds(_config.MetricsSampleIntervalSec))).ConfigureAwait(false);
                if (finished == allWorkers)
                {
                    break;
                }
            }
        }
        catch
        {
            cts.Cancel();
            throw;
        }

        int exitCode = 0;
        try
        {
            await allWorkers.ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            exitCode = 1;
            Console.Error.WriteLine($"worker_error={ex}");
        }

        long producedDocs = 0;
        if (producer is not null)
        {
            try
            {
                producedDocs = await producer.ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                exitCode = 1;
                Console.Error.WriteLine($"producer_error={ex}");
            }
        }

        var results = metrics.Select(m => m.ResultSnapshot()).ToList();

        // Final aggregate line with resolved total docs.
        long? finalTotal = liveTotalDocs ?? (producer is not null ? producedDocs : null);
        var finalSnapshots = metrics.Select(m => m.LiveSnapshot()).ToList();
        string finalLine = _reporter.BuildAggregateLine(finalSnapshots, finalTotal, _config.ClientProcesses, aggregateThroughputSamples);
        _reporter.PrintLiveLine(finalLine, final: true);

        double totalElapsed = Math.Max(Clock.Now - totalStartedAt, 0.000001);
        _reporter.PrintParentResult(results, totalElapsed);

        long errorsTotal = results.Sum(r => r.Errors);
        if (errorsTotal > 0)
        {
            exitCode = 1;
        }

        return exitCode;
    }
}
