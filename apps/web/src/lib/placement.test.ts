import { describe, expect, it } from "vitest";
import { placementOf, zoneOf } from "./placement";

const fields = (f: Record<string, string>) => ({ fields: f });

describe("placement", () => {
  it("reads position, size, layer and board outline from the line's fields", () => {
    const p = placementOf(
      fields({
        "pcb.x": "22",
        "pcb.y": "18",
        "pcb.w": "5",
        "pcb.h": "5",
        "pcb.layer": "F.Cu",
        "pcb.board": "0,0,60,40",
      }),
    );
    expect(p).toEqual({
      x: 22,
      y: 18,
      w: 5,
      h: 5,
      sized: true,
      layer: "F.Cu",
      board: { x0: 0, y0: 0, x1: 60, y1: 40 },
    });
  });

  it("is undefined without coordinates or with a broken outline", () => {
    expect(placementOf(fields({}))).toBeUndefined();
    expect(placementOf(fields({ "pcb.x": "1", "pcb.y": "1" }))).toBeUndefined();
    expect(
      placementOf(fields({ "pcb.x": "1", "pcb.y": "x", "pcb.board": "0,0,1,1" })),
    ).toBeUndefined();
    expect(
      placementOf(fields({ "pcb.x": "1", "pcb.y": "1", "pcb.board": "5,5,1,1" })),
    ).toBeUndefined();
  });

  it("maps a point to the sheet zone (A–H across, 1–6 down)", () => {
    const board = "0,0,80,60";
    const z = (x: number, y: number) =>
      zoneOf(
        placementOf(
          fields({ "pcb.x": String(x), "pcb.y": String(y), "pcb.board": board }),
        ) as never,
      );
    expect(z(0, 0)).toBe("A1");
    expect(z(25, 25)).toBe("C3");
    expect(z(80, 60)).toBe("H6");
    expect(z(-5, 200)).toBe("A6");
  });
});
