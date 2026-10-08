import { ClickAwayListener, FormControl, FormHelperText, IconButton, Select, TextField, Tooltip, type SelectProps, type TextFieldProps } from "@mui/material";
import { useId, useRef, useState, type ReactNode } from "react";
import { help, type HelpTopic } from "../help";

export function HelpTip({ topic }: { topic: HelpTopic }) {
  const [open, setOpen] = useState(false);
  const dismissed = useRef(false);
  const [title, description] = help[topic];
  return <ClickAwayListener onClickAway={() => setOpen(false)}><span className="help-tip">
    <Tooltip title={description} open={open} placement="top" describeChild disableFocusListener disableTouchListener arrow
      slotProps={{ tooltip: { sx: { bgcolor: "background.paper", color: "text.primary", border: "1px solid", borderColor: "divider", boxShadow: 3, fontSize: 14, lineHeight: 1.5, p: 1.5, boxSizing: "border-box", maxWidth: "min(360px, calc(100vw - 32px))" } }, arrow: { sx: { color: "background.paper" } }, popper: { modifiers: [{ name: "offset", options: { offset: [0, 8] } }, { name: "preventOverflow", options: { padding: 12 } }] } }}
      onOpen={() => { if (!dismissed.current) setOpen(true); }} onClose={() => setOpen(false)}>
      <IconButton size="small" aria-label={`About ${title}`} onClick={() => { dismissed.current = false; setOpen(true); }}
        onFocus={() => { if (!dismissed.current) setOpen(true); }} onBlur={() => { dismissed.current = false; setOpen(false); }}
        onMouseLeave={() => { dismissed.current = false; }} onKeyDown={(event) => {
        if (event.key === "Escape") { event.stopPropagation(); dismissed.current = true; setOpen(false); }
      }}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4" /><circle cx="12" cy="17" r=".8" fill="currentColor" /></svg></IconButton>
    </Tooltip>
  </span></ClickAwayListener>;
}

export function HelpField({ topic, label, id, children, tour = false, grow = false, required = false }: { topic: HelpTopic; label: ReactNode; id: string; children: ReactNode; tour?: boolean; grow?: boolean; required?: boolean }) {
  return <div className={`help-field${grow ? " help-field-grow" : ""}`} data-tour={tour ? topic : undefined}><div className="help-field-heading"><label htmlFor={id} id={`${id}-label`}>{label}{required && <span aria-hidden="true"> *</span>}</label><HelpTip topic={topic} /></div>{children}</div>;
}

export function HelpTextField({ topic, tour, label, grow, ...props }: TextFieldProps & { topic: HelpTopic; tour?: boolean; label: ReactNode; grow?: boolean }) {
  const generated = useId();
  const id = props.id ?? generated;
  return <HelpField topic={topic} tour={tour} label={label} id={id} grow={grow} required={props.required}><TextField fullWidth {...props} id={id} /></HelpField>;
}

export function HelpSelectField<Value>({ topic, tour, label, helperText, children, ...props }: SelectProps<Value> & { topic: HelpTopic; tour?: boolean; label: ReactNode; helperText?: ReactNode }) {
  const generated = useId();
  const id = props.id ?? generated;
  return <HelpField topic={topic} tour={tour} label={label} id={id} required={props.required}><FormControl fullWidth disabled={props.disabled} error={props.error} required={props.required} size={props.size}>
    <Select {...props} id={id} labelId={`${id}-label`} aria-describedby={helperText ? `${id}-help` : props["aria-describedby"]}>{children}</Select>{helperText && <FormHelperText id={`${id}-help`}>{helperText}</FormHelperText>}
  </FormControl></HelpField>;
}

export function HelpControl({ topic, children, tour = false }: { topic: HelpTopic; children: ReactNode; tour?: boolean }) {
  return <div className="help-control" data-tour={tour ? topic : undefined}>{children}<HelpTip topic={topic} /></div>;
}

export function HelpLabel({ topic, children }: { topic: HelpTopic; children: ReactNode }) {
  return <span className="help-label"><span>{children}</span><HelpTip topic={topic} /></span>;
}
