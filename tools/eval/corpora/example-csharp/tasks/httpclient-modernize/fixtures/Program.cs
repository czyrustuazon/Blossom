using System;
using System.Net;

namespace LegacyApp;

class Program
{
    static void Main()
    {
        var client = new WebClient();
        var html = client.DownloadString("https://example.com/");
        Console.WriteLine(html.Length);
    }
}
