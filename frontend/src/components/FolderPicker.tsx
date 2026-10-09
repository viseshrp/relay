import { PathDisplay } from "./PathDisplay";
import { Alert, Autocomplete, Button, TextField, List, ListItem, ListItemButton, ListItemText, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import type { FolderListing } from "../types";
import { ActionIcon } from "./ActionIcon";

export function FolderPicker({ disabled, onSelect }: { disabled: boolean; onSelect: (path: string) => void }) {
  const [path, setPath] = useState<string | null>(null);
  const [listing, setListing] = useState<FolderListing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void api<FolderListing>(`/api/projects/folders${path ? `?path=${encodeURIComponent(path)}` : ""}`, { signal: controller.signal })
      .then((response) => { if (!controller.signal.aborted) setListing(response); })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorMessage(caught)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [path, revision]);
  async function more() {
    if (!listing?.next) return;
    setLoading(true);
    try {
      const query = new URLSearchParams({ path: listing.path, since: listing.next });
      const response = await api<FolderListing>(`/api/projects/folders?${query}`);
      setListing((current) => current?.path === response.path ? { ...response, folders: [...current.folders, ...response.folders] } : current);
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setLoading(false); }
  }
  return <Stack spacing={1} component="section" aria-label="Browse repository folders" aria-busy={loading}>
    <Typography variant="subtitle2">Browse folders</Typography>
    <Autocomplete freeSolo options={(listing?.folders ?? []).map(folder => folder.path)} onChange={(_, value) => { if (value) setPath(value); }} renderInput={parameters => <TextField {...parameters} label="Go to folder" helperText="Choose a suggested child folder or type a path, then press Enter." onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); const value = (event.target as HTMLInputElement).value; if (value) setPath(value); } }} />} />
    <Typography variant="body2" color="text.secondary">Choose a folder inside your home directory, or enter a repository path above.</Typography>
    {error && <Alert severity="error" action={<Button onClick={() => setRevision((value) => value + 1)}>Retry</Button>}>{error}</Alert>}
    {listing && <>
      <PathDisplay path={listing.path} label="current folder" display={listing.path === listing.root ? "Home folder" : undefined} />
      <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
        <Button disabled={disabled || loading || !listing.parent} onClick={() => setPath(listing.parent)}>Up one folder</Button>
        <Button disabled={disabled || loading || path === null} onClick={() => setPath(null)}>Home folder</Button>
        <Button variant="outlined" disabled={disabled || loading || Boolean(error)} onClick={() => onSelect(listing.path)}>Use this folder</Button>
      </Stack>
      <List sx={{ maxHeight: 280, overflowY: "auto" }} aria-label="Folders">
        {listing.folders.map((folder) => <ListItem key={folder.name} disablePadding><ListItemButton component="button" sx={{ width: "100%", textAlign: "left", gap: 1, "& > svg": { flexShrink: 0 }, "& .MuiListItemText-root": { minWidth: 0, overflowWrap: "anywhere" } }} disabled={disabled || loading} onClick={() => setPath(folder.path)}>
          <ActionIcon name="folder" /><ListItemText primary={folder.name} secondary={folder.repository ? "Git repository" : undefined} />
        </ListItemButton></ListItem>)}
      </List>
      {!loading && !error && !listing.folders.length && <Typography>No subfolders in this directory.</Typography>}
      {listing.next && <Button disabled={disabled || loading} onClick={() => void more()}>Load more folders</Button>}
    </>}
    {loading && <Typography>Loading folders…</Typography>}
  </Stack>;
}
