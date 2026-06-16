using System.Globalization;

namespace CosmosVectorBench;

/// <summary>
/// Command entrypoint for the .NET Cosmos DB write benchmark.
/// Parses CLI overrides, applies them as environment variables (mirroring the Python <c>main.py</c>),
/// loads configuration, and dispatches to the fake-data or file-input benchmark mode.
/// </summary>
public static class Program
{
    public static async Task<int> Main(string[] args)
    {
        try
        {
            ApplyOverrides(ParseArgs(args));
        }
        catch (ArgumentException ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 2;
        }

        BenchmarkConfig config;
        try
        {
            config = BenchmarkConfig.Load();
        }
        catch (InvalidOperationException ex)
        {
            Console.Error.WriteLine($"Configuration error: {ex.Message}");
            return 2;
        }

        Console.Write("\n");
        Console.WriteLine(
            $"Starting up benchmark run for num_clients={config.ClientProcesses}, " +
            $"bulk_size={config.BulkSize}, max_documents={config.EffectiveTotalDocs}");

        var benchmark = new Benchmark(config);
        return await benchmark.RunAsync().ConfigureAwait(false);
    }

    private sealed class CliArgs
    {
        public int? NumClients { get; set; }
        public int? BulkSize { get; set; }
        public int? TotalDocs { get; set; }
        public string? DataType { get; set; }
        public string? DataPath { get; set; }
        public string? ContainerName { get; set; }
    }

    private static CliArgs ParseArgs(string[] args)
    {
        var parsed = new CliArgs();
        for (int i = 0; i < args.Length; i++)
        {
            string arg = args[i];
            switch (arg)
            {
                case "--num-clients" or "--num_clients":
                    parsed.NumClients = PositiveInt(NextValue(args, ref i, arg), arg);
                    break;
                case "--bulk-size" or "--bulk_size":
                    parsed.BulkSize = PositiveInt(NextValue(args, ref i, arg), arg);
                    break;
                case "--total-docs" or "--total_docs":
                    parsed.TotalDocs = PositiveInt(NextValue(args, ref i, arg), arg);
                    break;
                case "--data-type" or "--data_type":
                    parsed.DataType = DataTypeValue(NextValue(args, ref i, arg), arg);
                    break;
                case "--data-path" or "--data_path":
                    parsed.DataPath = NextValue(args, ref i, arg);
                    break;
                case "--container-name" or "--container_name":
                    parsed.ContainerName = NextValue(args, ref i, arg);
                    break;
                case "-h" or "--help":
                    PrintUsage();
                    Environment.Exit(0);
                    break;
                default:
                    throw new ArgumentException($"Unknown argument: {arg}");
            }
        }

        return parsed;
    }

    private static void ApplyOverrides(CliArgs args)
    {
        if (args.NumClients is int numClients)
        {
            string value = numClients.ToString(CultureInfo.InvariantCulture);
            Environment.SetEnvironmentVariable("NUM_CLIENTS", value);
            Environment.SetEnvironmentVariable("CLIENTS", value);
            Environment.SetEnvironmentVariable("CLIENT_PROCESSES", value);
        }

        if (args.BulkSize is int bulkSize)
        {
            Environment.SetEnvironmentVariable("BULK_SIZE", bulkSize.ToString(CultureInfo.InvariantCulture));
        }

        if (args.TotalDocs is int totalDocs)
        {
            string value = totalDocs.ToString(CultureInfo.InvariantCulture);
            Environment.SetEnvironmentVariable("TOTAL_DOCS", value);
            Environment.SetEnvironmentVariable("MAX_TOTAL_DOCS", value);
        }

        if (!string.IsNullOrEmpty(args.DataType))
        {
            Environment.SetEnvironmentVariable("DATA_TYPE", args.DataType);
        }

        if (!string.IsNullOrEmpty(args.DataPath))
        {
            Environment.SetEnvironmentVariable("DATA_TYPE", "file");
            Environment.SetEnvironmentVariable("DOC_JSON_PATH", args.DataPath);
        }

        if (!string.IsNullOrEmpty(args.ContainerName))
        {
            Environment.SetEnvironmentVariable("COSMOS_CONTAINER_NAME", args.ContainerName);
        }
    }

    private static string NextValue(string[] args, ref int i, string flag)
    {
        if (i + 1 >= args.Length)
        {
            throw new ArgumentException($"{flag} requires a value");
        }

        return args[++i];
    }

    private static int PositiveInt(string value, string flag)
    {
        if (!int.TryParse(value.Replace("_", "").Replace(",", ""), NumberStyles.Integer, CultureInfo.InvariantCulture, out int parsed))
        {
            throw new ArgumentException($"{flag}: '{value}' must be an integer");
        }

        if (parsed < 1)
        {
            throw new ArgumentException($"{flag}: '{value}' must be >= 1");
        }

        return parsed;
    }

    private static string DataTypeValue(string value, string flag)
    {
        string normalized = value.Trim().ToLowerInvariant();
        return normalized switch
        {
            "fake" => "fake",
            "file" or "json" => "file",
            _ => throw new ArgumentException($"{flag}: '{value}' must be one of: fake, file, json"),
        };
    }

    private static void PrintUsage()
    {
        Console.WriteLine("Run the Cosmos DB write benchmark (.NET).");
        Console.WriteLine();
        Console.WriteLine("Options:");
        Console.WriteLine("  --num-clients <n>      Override NUM_CLIENTS from .env.");
        Console.WriteLine("  --bulk-size <n>        Override BULK_SIZE from .env.");
        Console.WriteLine("  --total-docs <n>       Override TOTAL_DOCS and MAX_TOTAL_DOCS from .env.");
        Console.WriteLine("  --data-type <type>     Select data source: fake | file | json (json is an alias for file).");
        Console.WriteLine("  --data-path <path>     Override DOC_JSON_PATH and run with DATA_TYPE=file.");
        Console.WriteLine("  --container-name <name> Override COSMOS_CONTAINER_NAME from .env.");
    }
}
