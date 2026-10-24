
import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

const h = React.createElement;

function MotionVisual() {
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    document.documentElement.classList.add("rdx-motion-ready");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) return undefined;
    const timer = window.setInterval(() => setPhase(value => (value + 1) % 4), 2200);
    return () => window.clearInterval(timer);
  }, []);

  return h("div", { className: "rdx-motion-scene", "data-phase": phase, role: "presentation" },
    h("div", { className: "rdx-code-card" },
      h("div", { className: "rdx-windowbar" },
        h("i"), h("i"), h("i"),
        h("b", null, "animation.html")
      ),
      h("div", { className: "rdx-code-lines" },
        h("div", { className: "rdx-code-row" },
          h("span", { className: "rdx-line-num" }, "01"),
          h("span", { className: "rdx-code-token" }, "const"),
          h("span", null, "scene"),
          h("span", { className: "rdx-code-punct" }, "=")
        ),
        h("div", { className: "rdx-code-row" },
          h("span", { className: "rdx-line-num" }, "02"),
          h("span", { className: "rdx-code-token" }, "animate"),
          h("span", { className: "rdx-code-punct" }, "("),
          h("span", { className: "rdx-code-string" }, "\"motion\""),
          h("span", { className: "rdx-code-punct" }, ")")
        ),
        h("div", { className: "rdx-code-row" },
          h("span", { className: "rdx-line-num" }, "03"),
          h("span", { className: "rdx-code-string" }, "render(frame)")
        ),
        h("div", { className: "rdx-code-row" },
          h("span", { className: "rdx-line-num" }, "04"),
          h("span", { className: "rdx-code-punct" }, "→"),
          h("span", { className: "rdx-code-token" }, "MP4")
        )
      ),
      h("div", { className: "rdx-code-progress" }, h("span"))
    ),
    h("div", { className: "rdx-convert-badge", "aria-hidden": "true" }, "→"),
    h("div", { className: "rdx-video-card" },
      h("div", { className: "rdx-film-frame" },
        h("div", { className: "rdx-film-sun" }),
        h("div", { className: "rdx-film-hill" }),
        h("div", { className: "rdx-film-hill alt" }),
        h("div", { className: "rdx-play" }, "▶")
      ),
      h("div", { className: "rdx-video-caption" },
        h("span", null, "RENDRAX.mp4"),
        h("span", null, "00:12")
      )
    ),
    h("div", { className: "rdx-float-pill rdx-pill-secure" },
      h("span", { className: "rdx-live-dot" }),
      "Rendu sécurisé"
    ),
    h("div", { className: "rdx-float-pill rdx-pill-quality" },
      h("span", null, "✳"),
      h("span", null, "Image par image")
    )
  );
}

const mount = document.getElementById("rdx-react-visual");
if (mount) {
  try {
    createRoot(mount).render(h(MotionVisual));
  } catch (error) {
    console.error("RENDRAX motion UI failed to mount", error);
  }
}
