import { Alert, Button, Modal, Space } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactQuill from "react-quill-new";
import "react-quill-new/dist/quill.snow.css";

const modules = {
  toolbar: [
    [{ header: [1, 2, 3, false] }],
    ["bold", "italic", "underline", "strike"],
    [{ list: "ordered" }, { list: "bullet" }],
    [{ color: [] }, { background: [] }],
    ["link"],
    ["clean"],
  ],
};

const formats = [
  "header",
  "bold",
  "italic",
  "underline",
  "strike",
  "list",
  "bullet",
  "color",
  "background",
  "link",
];

const getPlainTextLength = (html: string): number => {
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  return tmp.textContent?.length || 0;
};

const countLines = (html: string): number => {
  if (!html) return 0;
  const lines = html.split(/<\/p>|<br>/gi).filter((line) => {
    const tmp = document.createElement("div");
    tmp.innerHTML = line;
    return (tmp.textContent?.trim().length || 0) > 0;
  });
  return lines.length;
};

const getMaxCharsPerLine = (html: string): number => {
  if (!html) return 0;
  const lines = html.split(/<\/p>|<br>/gi).map((line) => {
    const tmp = document.createElement("div");
    tmp.innerHTML = line;
    return tmp.textContent?.trim().length || 0;
  });
  return Math.max(...lines, 0);
};

interface ValidationState {
  lines: number;
  chars: number;
  maxLineLength?: number;
  valid: boolean;
  warnings: string[];
}

interface RichTextEditorModalProps {
  visible: boolean;
  onClose: () => void;
  value?: string;
  onSave: (content: string) => void;
  title?: string;
  /** Pin above a parent modal when opened from inside one (sibling modals
   *  don't get AntD's nesting auto-lift). Pass 1100 from a modal call site. */
  zIndex?: number;
  placeholder?: string;
  maxLines?: number | null;
  maxCharacters?: number | null;
  maxCharsPerLine?: number | null;
  warningLines?: number | null;
  warningCharacters?: number | null;
  warningCharsPerLine?: number | null;
}

export default function RichTextEditorModal({
  visible,
  onClose,
  value,
  onSave,
  title,
  zIndex,
  placeholder,
  maxLines = null,
  maxCharacters = null,
  maxCharsPerLine = null,
  warningLines = null,
  warningCharacters = null,
  warningCharsPerLine = null,
}: RichTextEditorModalProps) {
  const { t } = useTranslation();
  // The caller (SettingsPage) gives this component a fresh React
  // ``key`` on every open, so ``useState(value || "")`` initialises
  // with the value just passed in. No need for any session-tracking
  // inside the modal — the parent's key bump handles the mount story.
  const [content, setContent] = useState(value || "");
  const [validation, setValidation] = useState<ValidationState>({
    lines: 0,
    chars: 0,
    valid: true,
    warnings: [],
  });

  const validateContent = useCallback((html: string) => {
    const lines = countLines(html);
    const chars = getPlainTextLength(html);
    const maxLineLength = getMaxCharsPerLine(html);
    const warnings: string[] = [];
    let valid = true;

    if (maxLines && lines > maxLines) {
      warnings.push(
        t("validation.too_many_lines", {
          maxLines,
          lines,
          defaultValue: `Text exceeds ${maxLines} line(s). Current: ${lines}`,
        }),
      );
      valid = false;
    } else if (warningLines && lines >= warningLines) {
      warnings.push(
        t("validation.approaching_line_limit", {
          lines,
          maxLines,
          defaultValue: `Approaching line limit (${lines}/${maxLines})`,
        }),
      );
    }

    if (maxCharacters && chars > maxCharacters) {
      warnings.push(
        t("validation.too_many_characters", {
          maxCharacters,
          chars,
          defaultValue: `Text exceeds ${maxCharacters} characters. Current: ${chars}`,
        }),
      );
      valid = false;
    } else if (warningCharacters && chars >= warningCharacters) {
      warnings.push(
        t("validation.approaching_char_limit", {
          chars,
          maxCharacters,
          defaultValue: `Approaching character limit (${chars}/${maxCharacters})`,
        }),
      );
    }

    if (maxCharsPerLine && maxLineLength > maxCharsPerLine) {
      warnings.push(
        t("validation.line_too_long", {
          maxCharsPerLine,
          maxLineLength,
          defaultValue: `One line exceeds ${maxCharsPerLine} characters. Longest line: ${maxLineLength}`,
        }),
      );
      valid = false;
    } else if (warningCharsPerLine && maxLineLength >= warningCharsPerLine) {
      warnings.push(
        t("validation.line_approaching_limit", {
          maxLineLength,
          maxCharsPerLine,
          defaultValue: `One line approaching ${maxCharsPerLine} character limit (${maxLineLength}/${maxCharsPerLine})`,
        }),
      );
    }

    setValidation({ lines, chars, maxLineLength, valid, warnings });
    return valid;
  }, [
    t,
    maxLines,
    warningLines,
    maxCharacters,
    warningCharacters,
    maxCharsPerLine,
    warningCharsPerLine,
  ]);

  useEffect(() => {
    if (visible) {
      setContent(value || "");
      validateContent(value || "");
    }
  }, [visible, value, validateContent]);

  const handleChange = (newContent: string) => {
    setContent(newContent);
    validateContent(newContent);
  };

  const handleSave = () => {
    onSave(content);
    onClose();
  };

  return (
    <Modal
      title={title || t("common.edit_description")}
      open={visible}
      onCancel={onClose}
      width={800}
      zIndex={zIndex}
      footer={
        <Space>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            onClick={handleSave}
            disabled={!validation.valid}
          >
            {t("common.save")}
          </Button>
        </Space>
      }
    >
      <div style={{ minHeight: "300px" }}>
        {validation.warnings.length > 0 && (
          <Alert
            message={
              validation.valid
                ? t("common.warning")
                : t("common.error")
            }
            description={
              <ul style={{ margin: 0, paddingLeft: "20px", fontSize: "12px" }}>
                {validation.warnings.map((warning, idx) => (
                  <li key={idx}>{warning}</li>
                ))}
              </ul>
            }
            type={validation.valid ? "warning" : "error"}
            showIcon
            banner
            style={{
              marginBottom: "12px",
              padding: "8px 12px",
              fontSize: "12px",
              borderRadius: "4px",
            }}
          />
        )}

        <div
          style={{
            marginBottom: "8px",
            fontSize: "12px",
            color: "var(--color-text-secondary)",
          }}
        >
          {maxLines && (
            <span style={{ marginRight: "16px" }}>
              {t("common.lines")}: {validation.lines}
              {maxLines && ` / ${maxLines}`}
            </span>
          )}
          {maxCharacters && (
            <span style={{ marginRight: "16px" }}>
              {t("common.characters")}: {validation.chars}
              {maxCharacters && ` / ${maxCharacters}`}
            </span>
          )}
          {maxCharsPerLine && (
            <span>
              {t("common.longest_line")}:{" "}
              {validation.maxLineLength}
              {maxCharsPerLine && ` / ${maxCharsPerLine}`}
            </span>
          )}
        </div>
        <ReactQuill
          theme="snow"
          value={content}
          onChange={handleChange}
          modules={modules}
          formats={formats}
          placeholder={
            placeholder ||
            t("common.enter_description")
          }
          style={{ height: "250px", marginBottom: "50px" }}
        />
      </div>
    </Modal>
  );
}
