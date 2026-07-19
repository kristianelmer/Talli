"use client";

import { useId, useState, type DragEvent } from "react";

import { FileText, UploadCloud } from "./Icons";

export type FileDropzoneProps = {
  /** Name of the hidden text input that carries the file content to the server action. */
  name: string;
  /** Instructional label shown before a file is chosen. */
  label: string;
  /** Secondary hint under the label (e.g. accepted formats). */
  hint?: string;
  /** Accept attribute, e.g. ".csv,text/csv". */
  accept?: string;
  /** Message shown when the chosen file is the wrong type or cannot be read. */
  fileError?: string;
  /** Builds the confirmation label from the chosen file name. */
  chosenLabel?: (fileName: string) => string;
  /** Receives the file's text content (and name) so a parent can render a preview. */
  onText?: (text: string, fileName: string) => void;
};

/**
 * Token-driven drag-and-drop file field. Reads the dropped/selected file as
 * text on the client and mirrors it into a hidden input so existing
 * text-based server actions keep working unchanged.
 */
export function FileDropzone({
  name,
  label,
  hint,
  accept = ".csv,text/csv",
  fileError = "Filen kunne ikke leses. Velg en CSV-fil.",
  chosenLabel = (fileName) => `Valgt fil: ${fileName}`,
  onText,
}: FileDropzoneProps) {
  const id = useId();
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | undefined>(undefined);

  const accepts = (file: File) => {
    const tokens = accept
      .split(",")
      .map((token) => token.trim().toLowerCase())
      .filter(Boolean);
    if (tokens.length === 0) {
      return true;
    }
    const lowerName = file.name.toLowerCase();
    const lowerType = file.type.toLowerCase();
    return tokens.some((token) =>
      token.startsWith(".") ? lowerName.endsWith(token) : lowerType === token,
    );
  };

  const readFile = (file: File) => {
    if (!accepts(file)) {
      setError(fileError);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const content = typeof reader.result === "string" ? reader.result : "";
      setText(content);
      setFileName(file.name);
      setError(undefined);
      onText?.(content, file.name);
    };
    reader.onerror = () => setError(fileError);
    reader.readAsText(file);
  };

  const handleDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) {
      readFile(file);
    }
  };

  const className = [
    "dropzone",
    dragging ? "dropzone--active" : "",
    error ? "dropzone--error" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="dropzoneField">
      <label
        htmlFor={id}
        className={className}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <span className="dropzoneIcon" aria-hidden>
          {fileName ? <FileText size={22} /> : <UploadCloud size={22} />}
        </span>
        <span className="dropzoneLabel">{fileName ? chosenLabel(fileName) : label}</span>
        {hint ? <span className="dropzoneHint">{hint}</span> : null}
        <input
          id={id}
          type="file"
          accept={accept}
          className="dropzoneInput"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) {
              readFile(file);
            }
          }}
        />
      </label>
      <input type="hidden" name={name} value={text} />
      {error ? (
        <p className="dropzoneError" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
