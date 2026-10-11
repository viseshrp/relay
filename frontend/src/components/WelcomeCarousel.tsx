import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
  useMediaQuery,
} from "@mui/material";
import useEmblaCarousel from "embla-carousel-react";
import { useEffect, useState } from "react";
import { rememberSeen, WELCOME_SEEN } from "../onboarding";
import {
  OnboardingIllustration,
  type IllustrationKind,
} from "./OnboardingIllustration";

const slides: { title: string; text: string; image: IllustrationKind }[] = [
  {
    title: "Start with your repository",
    text: "Open a local Git repository. Relay keeps workflows in its .relay folder and run data in local application storage. Agent work uses isolated working copies.",
    image: "project",
  },
  {
    title: "Draw your workflow",
    text: "Start from a template, then add agent work, commands, and human reviews. Select a stage to edit its settings. The canvas and YAML stay in sync.",
    image: "workflow",
  },
  {
    title: "See what happened",
    text: "Run workflow opens a summary with job status and elapsed time. Open a job for live output and log search. Relay shows review requests when your answer is needed.",
    image: "run",
  },
  {
    title: "Make Relay your own",
    text: "Settings holds global defaults, project overrides, and storage cleanup. Question-mark buttons explain controls. Choose Take the tour to see each area, or Skip introduction to start working.",
    image: "settings",
  },
];

export function WelcomeCarousel({
  onClose,
  onShowTour,
}: {
  onClose: () => void;
  onShowTour: () => void;
}) {
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const [viewport, embla] = useEmblaCarousel({
    loop: false,
    duration: reducedMotion ? 0 : 20,
  });
  const [selected, setSelected] = useState(0);
  useEffect(() => {
    rememberSeen(WELCOME_SEEN);
  }, []);
  useEffect(() => {
    // Consume Escape once so dismissal does not reach another overlay.
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.stopImmediatePropagation();
      onClose();
    };
    window.addEventListener("keyup", closeOnEscape, true);
    return () => window.removeEventListener("keyup", closeOnEscape, true);
  }, [onClose]);
  useEffect(() => {
    if (!embla) return;
    const sync = () => setSelected(embla.selectedScrollSnap());
    sync();
    embla.on("select", sync);
    embla.on("reInit", sync);
    return () => {
      embla.off("select", sync);
      embla.off("reInit", sync);
    };
  }, [embla]);
  return (
    <Dialog
      open
      onClose={(_event, reason) => {
        if (reason !== "escapeKeyDown") onClose();
      }}
      fullWidth
      maxWidth="lg"
      aria-labelledby="welcome-title"
      onKeyDown={(event) => {
        if (event.key === "ArrowRight") {
          event.preventDefault();
          embla?.scrollNext();
        }
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          embla?.scrollPrev();
        }
      }}
    >
      <DialogTitle id="welcome-title">Welcome to Relay</DialogTitle>
      <DialogContent>
        <div
          role="region"
          aria-roledescription="carousel"
          aria-label="Welcome slides"
          className="welcome-carousel"
        >
          <div ref={viewport} className="welcome-viewport">
            <div className="welcome-track">
              {slides.map((slide, index) => (
                <section
                  key={slide.image}
                  className="welcome-slide"
                  role="group"
                  aria-roledescription="slide"
                  aria-label={`${index + 1} of ${slides.length}`}
                  aria-hidden={selected !== index}
                >
                  <OnboardingIllustration kind={slide.image} />
                  <div className="welcome-slide-copy">
                    <Typography variant="overline" color="primary">
                      {String(index + 1).padStart(2, "0")} /{" "}
                      {String(slides.length).padStart(2, "0")}
                    </Typography>
                    <Typography component="h2" variant="h5">
                      {slide.title}
                    </Typography>
                    <Typography sx={{ mt: 2 }}>{slide.text}</Typography>
                  </div>
                </section>
              ))}
            </div>
          </div>
          <Stack
            direction="row"
            spacing={1}
            sx={{ mt: 2, justifyContent: "center" }}
          >
            {slides.map((slide, index) => (
              <Button
                key={slide.image}
                size="small"
                aria-label={`Show slide ${index + 1}: ${slide.title}`}
                aria-current={selected === index ? "step" : undefined}
                onClick={() => embla?.scrollTo(index)}
              >
                {index + 1}
              </Button>
            ))}
          </Stack>
          <Typography
            role="status"
            variant="body2"
            sx={{ textAlign: "center" }}
          >
            Slide {selected + 1} of {slides.length}
          </Typography>
        </div>
      </DialogContent>
      <DialogActions sx={{ flexWrap: "wrap", gap: 1 }}>
        <Button onClick={onClose}>Skip introduction</Button>
        <span style={{ flex: 1 }} />
        <Button disabled={selected === 0} onClick={() => embla?.scrollPrev()}>
          Back
        </Button>
        <Button
          variant="contained"
          onClick={() =>
            selected === slides.length - 1 ? onShowTour() : embla?.scrollNext()
          }
        >
          {selected === slides.length - 1 ? "Take the tour" : "Next"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
