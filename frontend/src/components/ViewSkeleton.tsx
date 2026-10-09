import { Box, Paper, Skeleton, Stack } from "@mui/material";

export function ViewSkeleton({
  view = "home",
  header = true,
}: {
  view?: string;
  header?: boolean;
}) {
  return (
    <Stack
      role="status"
      aria-label={`Loading ${view}`}
      aria-busy="true"
      spacing={2}
      className="view-skeleton"
    >
      {header && (
        <Box sx={{ minHeight: view === "summary" ? 150 : 80 }}>
          <Skeleton width="65%" height={40} />
          <Skeleton width="40%" />
        </Box>
      )}
      <Box className={view === "summary" ? "run-layout" : "actions-layout"}>
        {view !== "home" && (
          <Paper variant="outlined" className="skeleton-sidebar">
            <Stack spacing={2}>
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton key={index} height={32} />
              ))}
            </Stack>
          </Paper>
        )}
        <Paper
          variant="outlined"
          sx={{ p: 2, minHeight: 500, minWidth: 0, flex: 1 }}
        >
          <Skeleton height={56} />
          <Skeleton height={110} />
          <Skeleton height={80} />
          <Skeleton height={80} />
        </Paper>
      </Box>
    </Stack>
  );
}

export function LoadingShell({ view }: { view: string }) {
  return (
    <Box>
      <Box className="app-header skeleton-header">
        <Skeleton width={64} height={36} />
        <Skeleton className="project-context" width={260} height={40} />
        <Skeleton width={260} height={36} />
      </Box>
      <Box component="main" className="app-content">
        <ViewSkeleton view={view} />
      </Box>
    </Box>
  );
}
