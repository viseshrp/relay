import { ClickAwayListener, IconButton, Tooltip } from "@mui/material";
import { useRef, useState, type ReactNode } from "react";
import { help, type HelpTopic } from "../help";

export function HelpTip({ topic }: { topic: HelpTopic }) {
  const [open, setOpen] = useState(false);
  const dismissed = useRef(false);
  const [title, description] = help[topic];
  return <ClickAwayListener onClickAway={() => setOpen(false)}><span className="help-tip">
    <Tooltip title={description} open={open} describeChild disableFocusListener disableTouchListener arrow onOpen={() => { if (!dismissed.current) setOpen(true); }} onClose={() => setOpen(false)}>
      <IconButton size="small" aria-label={`About ${title}`} onClick={() => { dismissed.current = false; setOpen(true); }}
        onFocus={() => { if (!dismissed.current) setOpen(true); }} onBlur={() => { dismissed.current = false; setOpen(false); }}
        onMouseLeave={() => { dismissed.current = false; }} onKeyDown={(event) => {
        if (event.key === "Escape") { event.stopPropagation(); dismissed.current = true; setOpen(false); }
      }}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4" /><circle cx="12" cy="17" r=".8" fill="currentColor" /></svg></IconButton>
    </Tooltip>
  </span></ClickAwayListener>;
}

export function HelpField({ topic, children, tour = false }: { topic: HelpTopic; children: ReactNode; tour?: boolean }) {
  return <div className="help-field" data-tour={tour ? topic : undefined}><div className="help-field-control">{children}</div><HelpTip topic={topic} /></div>;
}

export function HelpLabel({ topic, children }: { topic: HelpTopic; children: ReactNode }) {
  return <span className="help-label">{children}<HelpTip topic={topic} /></span>;
}
