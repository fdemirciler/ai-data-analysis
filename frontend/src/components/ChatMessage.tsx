import { useState } from "react";
import { User, Bot, Copy, Download, Check } from "lucide-react";
import { Button } from "./ui/button";

interface ChatMessageProps {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  code?: string;
  chart?: any;
  table?: Array<Record<string, any>>;
  artifacts?: Array<{ type: string; url: string; filename: string }>;
  isStreaming?: boolean;
}

export function ChatMessage({ 
  role, 
  content, 
  timestamp, 
  code, 
  chart, 
  table, 
  artifacts, 
  isStreaming 
}: ChatMessageProps) {
  const [copied, setCopied] = useState(false);

  const copyToClipboard = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const timeLabel = (() => {
    const date = new Date(timestamp);
    return Number.isNaN(date.getTime())
      ? timestamp
      : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  })();

  const spinner = (
    <span className="inline-flex h-4 w-4 items-center justify-center align-middle ml-2">
      <span className="h-3 w-3 rounded-full border-2 border-gray-400 border-t-transparent animate-spin" />
    </span>
  );

  if (role === "user") {
    return (
      <div className="flex justify-center px-4">
        <div className="flex w-full max-w-3xl justify-end gap-3">
          <div className="flex flex-col items-end max-w-[70%] space-y-1">
            <div className="rounded-2xl bg-[#10a37f] px-4 py-2 text-sm text-white whitespace-pre-wrap break-words">
              {content}
            </div>
            <span className="text-xs text-gray-400 dark:text-gray-500">{timeLabel}</span>
          </div>
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#10a37f] text-white">
            <User className="h-4 w-4" />
          </div>
        </div>
      </div>
    );
  }

  const trimmed = content.trim();
  const displayText = trimmed || (isStreaming ? "Analyzing your data..." : "");
  const lines = displayText ? displayText.split("\n") : [];

  return (
    <div className="flex justify-center px-4">
      <div className="flex w-full max-w-3xl items-start gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#10a37f] text-white">
          <Bot className="h-4 w-4" />
        </div>
        <div className="flex-1 space-y-3">
          <div className="markdown prose w-full break-words text-gray-800 dark:text-gray-100">
            {lines.length > 0 ? (
              lines.map((line, index) => (
                <p key={index} className="mb-2 last:mb-0 flex items-center">
                  <span>{line}</span>
                  {isStreaming && index === lines.length - 1 && spinner}
                </p>
              ))
            ) : null}
          </div>

          {code && (
            <div className="bg-black rounded-md mb-4">
              <div className="flex items-center relative text-gray-200 bg-gray-800 px-4 py-2 text-xs font-sans justify-between rounded-t-md">
                <span>Code</span>
                <button
                  className="flex ml-auto gap-2"
                  onClick={() => copyToClipboard(code)}
                >
                  {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  {copied ? "Copied!" : "Copy code"}
                </button>
              </div>
              <div className="p-4 overflow-y-auto">
                <code className="!whitespace-pre text-gray-100 text-sm">
                  {code}
                </code>
              </div>
            </div>
          )}

          {chart && (
            <div className="bg-white dark:bg-gray-800 border rounded-lg p-4 mb-4">
              <div className="h-64 flex items-center justify-center text-gray-500">
                [Chart would render here with Chart.js]
              </div>
            </div>
          )}

          {table && table.length > 0 && (
            <div className="overflow-x-auto mb-4">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                <thead className="bg-gray-50 dark:bg-gray-800">
                  <tr>
                    {Object.keys(table[0]).map((header) => (
                      <th key={header} className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                  {table.slice(0, 10).map((row, index) => (
                    <tr key={index}>
                      {Object.values(row).map((cell, cellIndex) => (
                        <td key={cellIndex} className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
                          {String(cell)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {table.length > 10 && (
                <div className="px-4 py-2 bg-gray-50 dark:bg-gray-800 text-xs text-gray-500">
                  Showing 10 of {table.length} rows
                </div>
              )}
            </div>
          )}

          {artifacts && artifacts.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-4">
              {artifacts.map((artifact, index) => (
                <button
                  key={index}
                  onClick={() => window.open(artifact.url, "_blank")}
                  className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800 hover:bg-blue-200"
                >
                  <Download className="h-3 w-3 mr-1" />
                  {artifact.filename}
                </button>
              ))}
            </div>
          )}

          <div className="text-xs text-gray-400 dark:text-gray-500">{timeLabel}</div>
        </div>
      </div>
    </div>
  );
}