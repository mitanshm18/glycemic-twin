import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { RiskDial } from "@/components/twin/RiskDial";
import { useAnimatedNumber } from "@/lib/motion";
import { setMedia } from "./setup";

describe("animated values", () => {
  it("start from zero (no flash of the final value) and settle on the target", async () => {
    const { result } = renderHook(() => useAnimatedNumber(40, 60));
    expect(result.current).toBe(0);
    await waitFor(() => expect(result.current).toBe(40), { timeout: 1000 });
  });

  it("jump straight to the value under reduced motion", () => {
    setMedia("(prefers-reduced-motion: reduce)", true);
    const { result } = renderHook(() => useAnimatedNumber(40, 60));
    expect(result.current).toBe(40);
  });

  it("show nothing, not zero, when there is no value", () => {
    const { result } = renderHook(() => useAnimatedNumber(null));
    expect(result.current).toBeNull();
  });
});

describe("risk dial reveal", () => {
  it("keeps its meaning available as text throughout the animation", () => {
    render(<RiskDial probability={0.27} threshold={0.39} tone="success" label="27% estimated probability, alert threshold 39%" />);
    expect(screen.getByRole("img", { name: "27% estimated probability, alert threshold 39%" })).toBeInTheDocument();
  });

  it("shows the final number immediately under reduced motion", () => {
    setMedia("(prefers-reduced-motion: reduce)", true);
    render(<RiskDial probability={0.27} threshold={0.39} tone="success" label="27%" />);
    expect(screen.getByRole("img")).toHaveTextContent("27%");
  });
});
