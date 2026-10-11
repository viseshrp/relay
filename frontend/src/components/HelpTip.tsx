import {
  ClickAwayListener,
  FormControl,
  FormHelperText,
  IconButton,
  Select,
  TextField,
  Tooltip,
  type SelectProps,
  type TextFieldProps,
} from "@mui/material";
import {
  Children,
  isValidElement,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { help, type HelpTopic } from "../help";

export function HelpTip({ topic }: { topic: HelpTopic }) {
  const [open, setOpen] = useState(false);
  const dismissed = useRef(false);
  const icon = useRef<HTMLButtonElement | null>(null);
  const [boundary, setBoundary] = useState<HTMLElement | null>(null);
  function show(): void {
    setBoundary(icon.current?.closest<HTMLElement>(".MuiDialog-paper") ?? null);
    setOpen(true);
  }
  const [title, description] = help[topic];
  return (
    <ClickAwayListener onClickAway={() => setOpen(false)}>
      <span className="help-tip">
        <Tooltip
          title={
            <span>
              {description}
              <br />
              <a
                href="https://github.com/viseshrp/relay/blob/main/docs/web-ui.md"
                target="_blank"
                rel="noreferrer"
              >
                Read the guide
              </a>
            </span>
          }
          open={open}
          placement="top"
          describeChild
          disableFocusListener
          disableTouchListener
          arrow
          slotProps={{
            tooltip: {
              sx: {
                bgcolor: "background.paper",
                color: "text.primary",
                border: "1px solid",
                borderColor: "divider",
                boxShadow: 3,
                fontSize: 14,
                lineHeight: 1.5,
                p: 1.5,
                boxSizing: "border-box",
                maxWidth: "min(360px, calc(100vw - 32px))",
              },
            },
            arrow: { sx: { color: "background.paper" } },
            popper: {
              modifiers: [
                { name: "offset", options: { offset: [0, 8] } },
                {
                  name: "preventOverflow",
                  options: {
                    padding: 12,
                    boundary: boundary ?? "clippingParents",
                  },
                },
                {
                  name: "flip",
                  options: {
                    padding: 12,
                    boundary: boundary ?? "clippingParents",
                  },
                },
              ],
            },
          }}
          onOpen={() => {
            if (!dismissed.current) show();
          }}
          onClose={() => setOpen(false)}
        >
          <IconButton
            ref={icon}
            size="small"
            aria-label={`About ${title}`}
            onClick={() => {
              dismissed.current = false;
              show();
            }}
            onFocus={() => {
              if (!dismissed.current) show();
            }}
            onBlur={(event) => {
              if (!(
                event.relatedTarget instanceof Element &&
                event.relatedTarget.closest("[role=tooltip]")
              )) {
                dismissed.current = false;
                setOpen(false);
              }
            }}
            onMouseLeave={() => {
              dismissed.current = false;
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.stopPropagation();
                dismissed.current = true;
                setOpen(false);
              }
            }}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="9" />
              <path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4" />
              <circle cx="12" cy="17" r=".8" fill="currentColor" />
            </svg>
          </IconButton>
        </Tooltip>
      </span>
    </ClickAwayListener>
  );
}

type FieldWidth = "short" | "standard" | "wide" | "content";

export function HelpField({
  topic,
  label,
  id,
  children,
  tour = false,
  grow = false,
  required = false,
  compact = false,
  width = "standard",
}: {
  topic: HelpTopic;
  label: ReactNode;
  id: string;
  children: ReactNode;
  tour?: boolean;
  grow?: boolean;
  required?: boolean;
  compact?: boolean;
  width?: FieldWidth;
}) {
  return (
    <div
      className={`help-field field-width-${compact ? "short" : width}${grow ? " help-field-grow" : ""}${compact ? " help-field-compact" : ""}`}
      data-tour={tour ? topic : undefined}
    >
      <div className="help-field-heading">
        <label htmlFor={id} id={`${id}-label`}>
          {label}
          {required && <span aria-hidden="true"> *</span>}
        </label>
        <HelpTip topic={topic} />
      </div>
      {children}
    </div>
  );
}

export function HelpTextField({
  topic,
  tour,
  label,
  grow,
  compact,
  width,
  ...props
}: TextFieldProps & {
  topic: HelpTopic;
  tour?: boolean;
  label: ReactNode;
  grow?: boolean;
  compact?: boolean;
  width?: FieldWidth;
}) {
  const generated = useId();
  const id = props.id ?? generated;
  return (
    <HelpField
      topic={topic}
      tour={tour}
      label={label}
      id={id}
      grow={grow}
      required={props.required}
      compact={compact ?? props.type === "number"}
      width={
        width ??
        (props.multiline
          ? "content"
          : ["model", "sharedModel", "project", "workflowKey"].includes(topic)
            ? "wide"
            : "standard")
      }
    >
      <TextField fullWidth {...props} id={id} />
    </HelpField>
  );
}

export function HelpSelectField<Value>({
  topic,
  tour,
  label,
  helperText,
  children,
  placeholder,
  compact = false,
  width,
  ...props
}: SelectProps<Value> & {
  topic: HelpTopic;
  tour?: boolean;
  label: ReactNode;
  helperText?: ReactNode;
  placeholder?: ReactNode;
  compact?: boolean;
  width?: FieldWidth;
}) {
  const generated = useId();
  const id = props.id ?? generated;
  const emptyChoice = Children.toArray(children).find(
    (child) =>
      isValidElement<{ value?: unknown }>(child) && child.props.value === "",
  );
  const emptyLabel =
    placeholder ??
    (isValidElement<{ children?: ReactNode }>(emptyChoice)
      ? emptyChoice.props.children
      : undefined);
  const empty =
    props.value === "" ||
    (Array.isArray(props.value) && props.value.length === 0);
  return (
    <HelpField
      topic={topic}
      tour={tour}
      label={label}
      id={id}
      required={props.required}
      compact={compact}
      width={width}
    >
      <FormControl
        fullWidth
        disabled={props.disabled}
        error={props.error}
        required={props.required}
        size={props.size}
      >
        <Select
          {...props}
          displayEmpty
          renderValue={
            empty && emptyLabel !== undefined
              ? () => emptyLabel
              : props.renderValue
          }
          id={id}
          labelId={`${id}-label`}
          aria-describedby={
            helperText ? `${id}-help` : props["aria-describedby"]
          }
        >
          {children}
        </Select>
        {helperText && (
          <FormHelperText id={`${id}-help`}>{helperText}</FormHelperText>
        )}
      </FormControl>
    </HelpField>
  );
}

export function HelpControl({
  topic,
  children,
  tour = false,
}: {
  topic: HelpTopic;
  children: ReactNode;
  tour?: boolean;
}) {
  return (
    <div className="help-control" data-tour={tour ? topic : undefined}>
      {children}
      <HelpTip topic={topic} />
    </div>
  );
}

export function HelpLabel({
  topic,
  children,
}: {
  topic: HelpTopic;
  children: ReactNode;
}) {
  return (
    <span className="help-label">
      <span>{children}</span>
      <HelpTip topic={topic} />
    </span>
  );
}
