import React, { useState } from "react";
import { User, Bot, Copy, Download, Check } from "lucide-react";

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
  const [codeCopied, setCodeCopied] = useState(false);

  const copyToClipboard = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setCodeCopied(true);
    setTimeout(() => setCodeCopied(false), 2000);
  };

  const displayText = content.trim() || (isStreaming ? "Thinking..." : "");

  // Both user and assistant messages use the same left-aligned layout
  return (
    <div className="group w-full py-8 px-4">
      <div className="max-w-3xl mx-auto flex gap-6 items-start">
        {/* Avatar - always on left */}
        <div className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-white text-sm font-medium ${
          role === "user" 
            ? "bg-purple-600" 
            : "bg-emerald-600"
        }`}>
          {role === "user" ? (
            <User className="h-4 w-4" strokeWidth={2} />
          ) : (
            <Bot className="h-4 w-4" strokeWidth={2} />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {/* Message card */}
          <div className="bg-white dark:bg-gray-900 border border-black/10 rounded-xl px-5 py-4">
            <div className="space-y-4">
          {/* Text content */}
          {displayText && (
            <div className="text-[15px] leading-[1.7] text-gray-800 dark:text-gray-200">
              {displayText.split('\n').map((line, idx) => (
                <p key={idx} className="mb-4 last:mb-0">
                  {line || '\u00A0'}
                  {isStreaming && idx === displayText.split('\n').length - 1 && (
                    <span className="inline-flex ml-1 align-middle">
                      <span className="w-1 h-4 bg-gray-400 dark:bg-gray-500 animate-pulse" />
                    </span>
                  )}
                </p>
              ))}
            </div>
          )}

          {/* Code block */}
          {code && (
            <div className="rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
              <div className="flex items-center justify-between px-4 py-2 bg-gray-50 dark:bg-gray-800">
                <span className="text-xs font-medium text-gray-600 dark:text-gray-400">python</span>
                <button
                  onClick={() => copyToClipboard(code)}
                  className="flex items-center gap-1.5 px-2 py-1 text-xs text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200 transition-colors"
                >
                  {codeCopied ? (
                    <>
                      <Check className="h-3 w-3" />
                      <span>Copied</span>
                    </>
                  ) : (
                    <>
                      <Copy className="h-3 w-3" />
                      <span>Copy code</span>
                    </>
                  )}
                </button>
              </div>
              <div className="p-4 bg-[#1e1e1e] overflow-x-auto">
                <code className="text-[13px] text-gray-100 font-mono whitespace-pre leading-relaxed">{code}</code>
              </div>
            </div>
          )}

          {/* Chart */}
          {chart && (
            <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-6 bg-gray-50 dark:bg-gray-800">
              <div className="h-64 flex items-center justify-center text-gray-400 dark:text-gray-500 text-sm">
                📊 Chart visualization
              </div>
            </div>
          )}

          {/* Table */}
          {table && table.length > 0 && (
            <div className="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                      {Object.keys(table[0]).map((header) => (
                        <th
                          key={header}
                          className="px-4 py-2.5 text-left text-xs font-medium text-gray-600 dark:text-gray-400"
                        >
                          {header}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                    {table.slice(0, 10).map((row, idx) => (
                      <tr key={idx} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                        {Object.values(row).map((cell, cellIdx) => (
                          <td key={cellIdx} className="px-4 py-2.5 text-gray-900 dark:text-gray-100">
                            {String(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {table.length > 10 && (
                <div className="px-4 py-2 bg-gray-50 dark:bg-gray-800 text-xs text-gray-500 dark:text-gray-400">
                  Showing 10 of {table.length} rows
                </div>
              )}
            </div>
          )}

          {/* Artifacts */}
          {artifacts && artifacts.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {artifacts.map((artifact, idx) => (
                <button
                  key={idx}
                  onClick={() => window.open(artifact.url, "_blank")}
                  className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-sm bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors"
                >
                  <Download className="h-3.5 w-3.5" />
                  {artifact.filename}
                </button>
              ))}
            </div>
          )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}