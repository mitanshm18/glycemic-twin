import { fireEvent, render, screen } from "@testing-library/react";
import { SignalField } from "@/components/auth/SignalField";
import { ANCHORS, lean, motif, pointAt, tracePoints, yOf, type Frame } from "@/lib/signal";
import { setMedia } from "./setup";

const F: Frame = { width: 600, height: 188, top: 14, bottom: 26 };

describe("sign-in signal geometry", () => {
  it("tells the product's story: one meal stays in range, the next crosses 180", () => {
    const peak = (from: number, to: number) => Math.max(...Array.from({ length: 200 }, (_, i) => motif(from + ((to - from) * i) / 199)));
    expect(peak(0.1, 0.4)).toBeLessThan(180);
    expect(peak(0.5, 0.8)).toBeGreaterThan(180);
    const above = ANCHORS.find((a) => a.id === "above");
    expect(motif(above?.u ?? 0)).toBeGreaterThan(180);
  });

  it("stays inside the drawing", () => {
    for (const [x, y] of tracePoints(F)) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(F.width);
      expect(y).toBeGreaterThan(F.top);
      expect(y).toBeLessThan(F.height - F.bottom);
    }
  });

  it("leans toward the pointer by a few pixels at most, and only nearby", () => {
    const base = yOf(motif(0.3), F);
    const p = { x: 0.3 * F.width, y: base - 500, strength: 1 };
    expect(Math.abs(lean(p.x, base, p))).toBeLessThanOrEqual(6);
    expect(lean(p.x, base, p)).toBeLessThan(0); // toward the pointer (up)
    expect(Math.abs(lean(p.x + 300, base, p))).toBeLessThan(0.01);
    expect(lean(p.x, base, { ...p, strength: 0 })).toBe(0);
    expect(pointAt(p.x, F, null)[1]).toBeCloseTo(base, 5);
  });
});

describe("sign-in signal", () => {
  it("is hidden from assistive technology (the page text carries the meaning)", () => {
    const { container } = render(<SignalField />);
    expect(container.querySelector(".signal")).toHaveAttribute("aria-hidden", "true");
  });

  it("explains one point at a time, in product vocabulary, and Esc puts it away", () => {
    setMedia("(prefers-reduced-motion: reduce)", true); // interactive immediately, no entrance
    const { container } = render(<SignalField />);
    const anchors = container.querySelectorAll(".signal__anchor");
    expect(anchors).toHaveLength(3);
    fireEvent.click(anchors[0] as Element);
    expect(screen.getByText("Meal logged")).toBeInTheDocument();
    fireEvent.click(anchors[2] as Element);
    expect(screen.queryByText("Meal logged")).not.toBeInTheDocument();
    expect(screen.getByText("Above 180")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByText("Above 180")).not.toBeInTheDocument();
  });

  it("has no explorable points in the compact strip", () => {
    setMedia("(prefers-reduced-motion: reduce)", true);
    const { container } = render(<SignalField compact />);
    expect(container.querySelectorAll(".signal__anchor")).toHaveLength(0);
  });
});
