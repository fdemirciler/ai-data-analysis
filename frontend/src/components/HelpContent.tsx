import React from 'react';

export const HelpContent: React.FC = () => {
  return (
    <div className="p-4 text-sm text-muted-foreground">
      <h4 className="mb-2 font-semibold text-foreground">How to Use</h4>
      <p className="mb-3">
        This is an AI-powered data analyst. Start by uploading a CSV or Excel file using the paperclip icon. Once your file is processed, you can ask questions about your data in plain English.
      </p>
      <p className="mb-3">
        For example, you can ask for insights, summaries, or visualizations. To see the Python code used for the analysis, just ask: "show me the code".
      </p>

      <h4 className="mb-2 font-semibold text-foreground">Usage Limits</h4>
      <ul className="list-disc pl-5 space-y-1">
        <li>Up to 50 requests per day.</li>
        <li>File size limit: 20MB.</li>
        <li>Supported file types: CSV, Excel (.xlsx, .xls).</li>
      </ul>

      {/* blank line before Privacy header */}
      <h4 className="mt-3 mb-2 font-semibold text-foreground">Privacy</h4>
      <ul className="list-disc pl-5 space-y-1">
        <li>Privacy and Data Retention: All uploaded files and their associated data are automatically deleted 1 day after they are uploaded.</li>
        <li>Secure Access: All your access is authenticated, only you can access your data and analysis history.</li>
      </ul>
    </div>
  );
};