using System.Globalization;
using System.Text;

namespace CosmosVectorBench;

/// <summary>
/// Builds the live aggregate progress output and the final aggregated result, and writes the metrics CSV row.
/// Reproduces the column order, filename pattern, and excluded fields of the Python <c>_print_parent_result</c>
/// and <c>_write_metrics_csv</c> so .NET runs land in the same <c>results/</c> folder with comparable schema.
/// </summary>
public sealed class MetricsReporter
{
    private static readonly (string Name, double Ratio)[] Percentiles =
    [
        ("p50", 0.50),
        ("p90", 0.90),
        ("p99", 0.99),
    ];

    private readonly BenchmarkConfig _config;
    private int _lastLineCount;

    public MetricsReporter(BenchmarkConfig config) => _config = config;

    public void PrintLiveLine(string line, bool final = false)
    {
        var builder = new StringBuilder();
        builder.Append(ClearPreviousLiveBlock(_lastLineCount));
        builder.Append(line);
        if (final)
        {
            Console.WriteLine(builder.ToString());
        }
        else
        {
            Console.Write(builder.ToString());
        }

        _lastLineCount = Math.Max(1, line.Count(c => c == '\n') + 1);
    }

    private static string ClearPreviousLiveBlock(int lineCount)
    {
        if (lineCount <= 0)
        {
            return "";
        }

        var builder = new StringBuilder("\r\x1b[2K");
        for (int i = 0; i < lineCount - 1; i++)
        {
            builder.Append("\x1b[1A\r\x1b[2K");
        }

        return builder.ToString();
    }

    /// <summary>Builds the multi-line aggregate progress block from the latest per-worker snapshots.</summary>
    public string BuildAggregateLine(
        IReadOnlyList<MetricSnapshot> snapshots,
        long? totalDocs,
        int clientProcesses,
        List<double> aggregateThroughputSamples)
    {
        double elapsed = AggregateElapsed(snapshots);
        int activeClients = snapshots.Count;
        long successTotal = snapshots.Sum(s => s.Success);
        long errorsTotal = snapshots.Sum(s => s.Errors);
        long throttlesTotal = snapshots.Sum(s => s.ThrottlesWithRetry);
        long completedTotal = successTotal + errorsTotal;
        double throughputCurrent = snapshots.Sum(s => s.CurrentDocsPerSec);

        if (snapshots.Any(s => s.Started))
        {
            aggregateThroughputSamples.Add(throughputCurrent);
        }

        double meanThroughput = Stats.Mean(aggregateThroughputSamples);
        double maxThroughput = Stats.Max(aggregateThroughputSamples);
        double requestChargeTotal = snapshots.Sum(s => s.RequestChargeTotal);
        long requestChargeObservations = snapshots.Sum(s => s.RequestChargeObservations);
        double avgRu = Stats.SafeDiv(requestChargeTotal, requestChargeObservations);

        double serviceMean = Stats.Mean(snapshots.Select(s => s.ServiceTimeMeanMs).ToList());
        double serviceP50 = snapshots.Count > 0 ? snapshots.Max(s => s.ServiceTimeP50Ms) : 0.0;
        double serviceP90 = snapshots.Count > 0 ? snapshots.Max(s => s.ServiceTimeP90Ms) : 0.0;
        double serviceP99 = snapshots.Count > 0 ? snapshots.Max(s => s.ServiceTimeP99Ms) : 0.0;

        var lines = new List<string>
        {
            $"clients_active={activeClients}/{clientProcesses}",
            "  Progress",
            $"    elapsed={elapsed.ToString("F1", CultureInfo.InvariantCulture)}s",
            $"    clients_active={activeClients}/{clientProcesses}",
            $"    completed={FormatCompleted(completedTotal, totalDocs)}",
            "  Throughput",
            $"    current_docs/sec={F2(throughputCurrent)}, current_docs/sec/client={F2(Stats.SafeDiv(throughputCurrent, Math.Max(clientProcesses, 1)))}",
            $"    mean_docs/sec={F2(meanThroughput)}, mean_docs/sec/client={F2(Stats.SafeDiv(meanThroughput, Math.Max(clientProcesses, 1)))}",
            $"    max_docs/sec={F2(maxThroughput)}",
            "  Timing",
            $"    service_time_ms_mean={F2(serviceMean)}, service_time_ms_p50={F2(serviceP50)}, service_time_ms_p90={F2(serviceP90)}, service_time_ms_p99={F2(serviceP99)}",
            "  Responses",
            $"    success={successTotal}, errors={errorsTotal}, throttles_w_retry={throttlesTotal}",
            $"    avg_ru_per_operation={F2(avgRu)}",
        };

        return string.Join("\n", lines);
    }

    /// <summary>Aggregates final per-worker results, prints the completion banner and final metrics, and writes the CSV row.</summary>
    public void PrintParentResult(IReadOnlyList<ResultSnapshot> results, double totalElapsedTimeSec)
    {
        long successTotal = results.Sum(r => r.Success);
        long errorsTotal = results.Sum(r => r.Errors);
        long docsCompleted = successTotal + errorsTotal;
        long throttlesTotal = results.Sum(r => r.ThrottlesWithRetry);
        int clientsCompleted = results.Count;

        double insertTimeSec = ResultElapsed(results);
        double fallbackThroughput = Stats.SafeDiv(successTotal, insertTimeSec);
        List<double> throughputSamples = SamplesOrFallback(AggregateThroughputSamples(results), fallbackThroughput);

        var serviceTimes = new List<double>();
        foreach (ResultSnapshot result in results)
        {
            serviceTimes.AddRange(result.ServiceTimeMsSamples);
        }

        double requestChargeTotal = results.Sum(r => r.RequestChargeTotal);
        long requestChargeObservations = results.Sum(r => r.RequestChargeObservations);

        double meanThroughput = Stats.Mean(throughputSamples);
        double maxThroughput = Stats.Max(throughputSamples);

        serviceTimes.Sort();

        var row = new (string Name, string Value)[]
        {
            ("total_elapsed_time_sec", F2(totalElapsedTimeSec)),
            ("insert_time_sec", F2(insertTimeSec)),
            ("metrics_sample_interval_sec", F2(_config.MetricsSampleIntervalSec)),
            ("metrics_timing_sample_interval", _config.MetricsTimingSampleInterval.ToString(CultureInfo.InvariantCulture)),
            ("capture_ru_charges", _config.CaptureRuCharges ? "true" : "false"),
            ("clients", _config.ClientProcesses.ToString(CultureInfo.InvariantCulture)),
            ("clients_completed", clientsCompleted.ToString(CultureInfo.InvariantCulture)),
            ("docs_completed", docsCompleted.ToString(CultureInfo.InvariantCulture)),
            ("success_total", successTotal.ToString(CultureInfo.InvariantCulture)),
            ("errors_total", errorsTotal.ToString(CultureInfo.InvariantCulture)),
            ("throttles_w_retry_total", throttlesTotal.ToString(CultureInfo.InvariantCulture)),
            ("mean_docs_per_sec", F2(meanThroughput)),
            ("mean_docs_per_sec_per_client", F2(Stats.SafeDiv(meanThroughput, Math.Max(_config.ClientProcesses, 1)))),
            ("max_docs_per_sec", F2(maxThroughput)),
            ("service_time_ms_mean", F2(Stats.Mean(serviceTimes))),
            ("service_time_ms_p50", F2(Stats.Percentile(serviceTimes, 0.50))),
            ("service_time_ms_p90", F2(Stats.Percentile(serviceTimes, 0.90))),
            ("service_time_ms_p99", F2(Stats.Percentile(serviceTimes, 0.99))),
            ("bulk_size", _config.BulkSize.ToString(CultureInfo.InvariantCulture)),
            ("bulks_started", results.Sum(r => r.BulksStarted).ToString(CultureInfo.InvariantCulture)),
            ("bulks_completed", results.Sum(r => r.BulksCompleted).ToString(CultureInfo.InvariantCulture)),
            ("bulk_success", results.Sum(r => r.BulkSuccess).ToString(CultureInfo.InvariantCulture)),
            ("bulk_errors", results.Sum(r => r.BulkErrors).ToString(CultureInfo.InvariantCulture)),
            ("bulk_docs_attempted", results.Sum(r => r.BulkDocsAttempted).ToString(CultureInfo.InvariantCulture)),
            ("bulk_docs_sampled", results.Sum(r => r.BulkDocsSampled).ToString(CultureInfo.InvariantCulture)),
            ("request_charge_total", F2(requestChargeTotal)),
            ("request_charge_observations", requestChargeObservations.ToString(CultureInfo.InvariantCulture)),
            ("avg_ru_per_operation", F2(Stats.SafeDiv(requestChargeTotal, requestChargeObservations))),
            ("max_total_docs", _config.MaxTotalDocs?.ToString(CultureInfo.InvariantCulture) ?? ""),
        };

        PrintFinalMetrics(row);
        WriteMetricsCsv(row);
    }

    private static void PrintFinalMetrics((string Name, string Value)[] row)
    {
        Console.WriteLine("\n***Benchmark completed!***\n");
        foreach ((string name, string value) in row)
        {
            Console.WriteLine($"     {name.Replace("_per_", "/")}={value}");
        }
    }

    private void WriteMetricsCsv((string Name, string Value)[] row)
    {
        if (!_config.CsvOutputEnabled)
        {
            return;
        }

        string fileName =
            $"{_config.RunStartedAt.ToString("MMddyy-HHmmss", CultureInfo.InvariantCulture)}" +
            $"-clients-{_config.ClientProcesses}" +
            $"-bulk-{_config.BulkSize}" +
            $"-maxdocs-{_config.TotalDocsLabel()}" +
            ".csv";

        string resultsRoot = Path.IsPathRooted(_config.TestResultsRoot)
            ? _config.TestResultsRoot
            : Path.Combine(_config.ProjectRoot, _config.TestResultsRoot);
        Directory.CreateDirectory(resultsRoot);
        string csvPath = Path.Combine(resultsRoot, fileName);

        bool writeHeader = !File.Exists(csvPath) || new FileInfo(csvPath).Length == 0;
        using var writer = new StreamWriter(csvPath, append: true, Encoding.UTF8);
        if (writeHeader)
        {
            writer.WriteLine(string.Join(",", row.Select(r => CsvField(r.Name))));
        }

        writer.WriteLine(string.Join(",", row.Select(r => CsvField(r.Value))));
        Console.WriteLine($"metrics_csv_path={csvPath}");
    }

    private static string CsvField(string value)
    {
        if (value.Contains(',') || value.Contains('"') || value.Contains('\n'))
        {
            return $"\"{value.Replace("\"", "\"\"")}\"";
        }

        return value;
    }

    private static double AggregateElapsed(IReadOnlyList<MetricSnapshot> snapshots)
    {
        var startedEpochs = snapshots.Where(s => s.StartedEpoch is > 0).Select(s => s.StartedEpoch!.Value).ToList();
        if (startedEpochs.Count == 0)
        {
            return 0.0;
        }

        return Math.Max(Clock.Epoch - startedEpochs.Min(), 0.000001);
    }

    private static double ResultElapsed(IReadOnlyList<ResultSnapshot> results)
    {
        var startedEpochs = results.Where(r => r.StartedEpoch is > 0).Select(r => r.StartedEpoch!.Value).ToList();
        var finishedEpochs = results.Where(r => r.FinishedEpoch is > 0).Select(r => r.FinishedEpoch!.Value).ToList();
        if (startedEpochs.Count == 0 || finishedEpochs.Count == 0)
        {
            return 0.0;
        }

        return Math.Max(finishedEpochs.Max() - startedEpochs.Min(), 0.000001);
    }

    private static List<double> AggregateThroughputSamples(IReadOnlyList<ResultSnapshot> results)
    {
        int maxLen = results.Count == 0 ? 0 : results.Max(r => r.ThroughputDocsPerSecSamples.Count);
        var aggregate = new List<double>(maxLen);
        for (int i = 0; i < maxLen; i++)
        {
            double sum = 0.0;
            bool any = false;
            foreach (ResultSnapshot result in results)
            {
                if (i < result.ThroughputDocsPerSecSamples.Count)
                {
                    sum += result.ThroughputDocsPerSecSamples[i];
                    any = true;
                }
            }

            if (any)
            {
                aggregate.Add(sum);
            }
        }

        return aggregate;
    }

    private List<double> SamplesOrFallback(List<double> samples, double fallback)
    {
        if (samples.Count > 0)
        {
            return samples;
        }

        if (_config.MetricsWarmupSec > 0)
        {
            return [];
        }

        return fallback > 0 ? [fallback] : [];
    }

    private static string FormatCompleted(long completed, long? totalDocs)
    {
        return totalDocs is null
            ? completed.ToString(CultureInfo.InvariantCulture)
            : $"{completed}/{totalDocs}";
    }

    private static string F2(double value) => value.ToString("F2", CultureInfo.InvariantCulture);
}
