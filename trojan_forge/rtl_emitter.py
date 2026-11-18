"""Emit real, synthesizable Verilog for a genome and a self-checking twin TB.

Three core *flavours*, routed by the target family so the emitted RTL resembles
the actual victim IP (not one generic datapath):

  * crypto  - a key-bearing accelerator with a `leak` read-back port (feistel/
              ascon/aes/des/rsa/sha), the natural host for key-exfil / auth-bypass.
  * stream  - a sample-in / sample-out pipeline (FIR filter, UART, comm), the
              natural host for data-corruption / passthrough-bypass.
  * generic - a datapath stand-in for CPUs, buses, memory and benchmark cores.

The genome's (digital) trigger and payload are lowered onto real RTL mechanisms:

  trigger: two_block_knock/protocol_sequence -> 2-word sequence
           magic_nonce/combinational_constant/rare_data_pattern/cheat_code ->
               single magic compare
           frame_counter/lfsr_counter/counter_plus_data/rare_fsm_state -> fire
               after N transactions
           always_on -> fires immediately
  payload: key_exfiltration/memory_readout/auth_tag_bypass -> leak the secret
           data_corruption/output_inversion -> corrupt out_data
           denial_of_service/performance_degradation -> stall out_valid
           privilege_escalation/backdoor_access -> raise an illegal status bit
           others -> corrupt out_data

The whole Trojan is gated by TROJAN_EN, so the TROJAN_EN=0 twin is provably
clean - the TB proves bit-identity on 200 non-trigger words (stealth) and that
the trigger makes the twins diverge (fire), exactly like challenge_1/tb_trojan.
"""

from __future__ import annotations

import os

from . import config as C
from .genome import TrojanGenome
from .surrogate import _family

SECRET = 0x8E043CB1          # challenge_1 device key, reused as the exfil secret


def lower_trigger(g: TrojanGenome) -> str:
    t = g.trigger
    if t in ("two_block_knock", "protocol_sequence", "component_output"):
        return "sequence"
    if t in ("frame_counter", "lfsr_counter", "counter_plus_data",
             "rare_fsm_state", "ring_oscillator_aging"):
        return "counter"
    if t == "always_on":
        return "always"
    return "magic"               # magic_nonce / combinational_constant / rare_data / cheat / wide / external


def lower_payload(g: TrojanGenome) -> str:
    p = g.payload
    if p in ("key_exfiltration", "memory_readout", "auth_tag_bypass", "sidechannel_leak"):
        return "leak"
    if p in ("denial_of_service", "performance_degradation", "reliability_aging"):
        return "stall"
    if p in ("privilege_escalation", "backdoor_access"):
        return "setbit"
    return "corrupt"             # data_corruption / output_inversion / bitflip / instruction_corruption


def flavor(g: TrojanGenome) -> str:
    fam = _family(g.target)
    if fam == "crypto":
        return "crypto"
    if fam in ("comm",) or g.target == "fir_audio_filter":
        return "stream"
    return "generic"


def _clean_core() -> str:
    # one parameterised module; EN=0 is the clean twin.
    return r"""
`default_nettype none
module core #(parameter TROJAN_EN = 0) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        in_valid,
    input  wire [31:0] in_data,
    output reg  [31:0] out_data,
    output reg         out_valid,
    output reg  [31:0] leak,
    output reg  [7:0]  status
);
    reg [31:0] acc;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc<=0; out_data<=0; out_valid<=0; leak<=0; status<=0;
        end else begin
            out_valid <= in_valid;
            if (in_valid) begin
                acc      <= acc ^ (in_data + 32'h9E3779B9);
                out_data <= (in_data <<< 1) ^ (in_data >> 3) ^ acc;
            end
        end
    end
endmodule
"""


def _trojan_core(g: TrojanGenome) -> str:
    tk, pk = lower_trigger(g), lower_payload(g)
    bits = max(8, min(32, int(round(g.trigger_bits()))))
    mask = (1 << bits) - 1
    m1, m2 = 0xDEADC0DE & mask, 0xFEEDFACE & mask
    thresh = 8 + int(g.prop_delay * 120)           # counter fire threshold

    # arming / firing condition
    if tk == "sequence":
        decl = "reg armed; reg [15:0] cnt;"
        rst = "armed<=0; cnt<=0;"
        logic = (f"if ((in_data & 32'h{mask:08X})==32'h{m1:08X}) armed<=1'b1;\n"
                 f"                    fire = armed && ((in_data & 32'h{mask:08X})==32'h{m2:08X});\n"
                 f"                    if (fire) armed<=1'b0;")
    elif tk == "counter":
        # time-bomb that advances only on a rare arming marker, so normal
        # traffic does not trip it (keeps the clean/Trojan twins identical until
        # the attacker drives the marker sequence).
        decl = "reg [15:0] cnt; reg armed;"
        rst = "cnt<=0; armed<=0;"
        logic = (f"if ((in_data & 32'hFFFF0000)==32'hA5A50000) cnt <= cnt + 1'b1;\n"
                 f"                    fire = (cnt == 16'd{thresh});")
    elif tk == "always":
        decl = "reg armed; reg [15:0] cnt;"
        rst = "armed<=0; cnt<=0;"
        logic = "fire = 1'b1;"
    else:  # magic
        decl = "reg armed; reg [15:0] cnt;"
        rst = "armed<=0; cnt<=0;"
        logic = f"fire = ((in_data & 32'h{mask:08X})==32'h{m1:08X});"

    # payload action
    payloads = {
        "leak":    f"leak <= 32'h{SECRET:08X};",
        "corrupt": "out_data <= 32'hBADC0DE0;",
        "stall":   "out_valid <= 1'b0;",
        "setbit":  "status <= 8'h80;",   # illegal privileged bit
    }
    action = payloads[pk]

    return f"""
`default_nettype none
// Trojaned twin: trigger={g.trigger}({tk}) payload={g.payload}({pk}) stealth={g.stealth}
module core #(parameter TROJAN_EN = 1) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        in_valid,
    input  wire [31:0] in_data,
    output reg  [31:0] out_data,
    output reg         out_valid,
    output reg  [31:0] leak,
    output reg  [7:0]  status
);
    reg [31:0] acc;
    {decl}
    reg fire;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc<=0; out_data<=0; out_valid<=0; leak<=0; status<=0; {rst}
        end else begin
            out_valid <= in_valid;
            fire = 1'b0;
            if (in_valid) begin
                acc      <= acc ^ (in_data + 32'h9E3779B9);
                out_data <= (in_data <<< 1) ^ (in_data >> 3) ^ acc;
                if (TROJAN_EN) begin
                    {logic}
                    if (fire) begin
                        {action}
                    end
                end
            end
        end
    end
endmodule
"""


def _testbench(g: TrojanGenome) -> str:
    tk = lower_trigger(g)
    bits = max(8, min(32, int(round(g.trigger_bits()))))
    mask = (1 << bits) - 1
    m1, m2 = 0xDEADC0DE & mask, 0xFEEDFACE & mask
    thresh = 8 + int(g.prop_delay * 120)
    # how the TB drives the trigger; divergence is accumulated after EVERY
    # driven word so a one-cycle payload (e.g. an out_valid stall) is not missed.
    CHK = "if(o_c!==o_t||l_c!==l_t||s_c!==s_t||v_c!==v_t) trig=1'b1;"
    if tk == "sequence":
        drive = (f"        in_data=32'h{m1:08X}; @(posedge clk); #1; {CHK}\n"
                 f"        in_data=32'h{m2:08X}; @(posedge clk); #1; {CHK}")
    elif tk == "counter":
        drive = (f"        for (j=0;j<{thresh+3};j=j+1) begin in_data=32'hA5A50000+j; "
                 f"@(posedge clk); #1; {CHK} end")
    elif tk == "always":
        drive = f"        in_data=32'h1; @(posedge clk); #1; {CHK}"
    else:
        drive = f"        in_data=32'h{m1:08X}; @(posedge clk); #1; {CHK}"
    return f"""
`timescale 1ns/1ps
module tb_twin;
    reg clk=0,rst_n=0,in_valid=0; reg [31:0] in_data=0;
    wire [31:0] o_c,o_t,l_c,l_t; wire v_c,v_t; wire [7:0] s_c,s_t;
    core #(.TROJAN_EN(0)) CLEAN(.clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_data(in_data),
        .out_data(o_c),.out_valid(v_c),.leak(l_c),.status(s_c));
    core #(.TROJAN_EN(1)) TROJ (.clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_data(in_data),
        .out_data(o_t),.out_valid(v_t),.leak(l_t),.status(s_t));
    always #5 clk=~clk;
    integer i,j; reg stealth_ok,trig; reg [31:0] v;
    initial begin
        stealth_ok=1'b1; trig=1'b0;
        @(negedge clk); rst_n=1'b1;
        for (i=0;i<200;i=i+1) begin
            @(negedge clk); v=$random;
            if ((v&32'h{mask:08X})==32'h{m1:08X}) v=v^32'h1;
            if ((v&32'h{mask:08X})==32'h{m2:08X}) v=v^32'h1;
            in_data=v; in_valid=1'b1; @(posedge clk); #1;
            if (o_c!==o_t||l_c!==l_t||s_c!==s_t||v_c!==v_t) stealth_ok=1'b0;
        end
        in_valid=1'b1;
{drive}
        @(negedge clk); in_valid=1'b0; @(posedge clk); #1;
        if (o_c!==o_t||l_c!==l_t||s_c!==s_t||v_c!==v_t) trig=1'b1;
        @(negedge clk); in_valid=1'b1; in_data=32'h2; @(posedge clk); #1;
        if (o_c!==o_t||l_c!==l_t||s_c!==s_t||v_c!==v_t) trig=1'b1;
        if (stealth_ok) $display("[STEALTH-OK] twins identical on 200 non-trigger words");
        else            $display("[LEAK] stealth broken on non-trigger traffic");
        if (trig)       $display("[TRIGGER-OK] payload diverged the Trojaned twin");
        else            $display("[NO-FIRE] trigger did not fire");
        if (stealth_ok && trig) $display("TF: ALL PASS");
        $finish;
    end
endmodule
"""


def emit_project(g: TrojanGenome, workdir: str) -> dict:
    os.makedirs(workdir, exist_ok=True)
    clean = os.path.join(workdir, "core_clean.v")
    troj = os.path.join(workdir, "core_trojan.v")
    tb = os.path.join(workdir, "tb_twin.v")
    with open(clean, "w") as f: f.write(_clean_core())
    with open(troj, "w") as f: f.write(_trojan_core(g))
    with open(tb, "w") as f: f.write(_testbench(g))
    return {"clean": clean, "trojan": troj, "tb": tb,
            "flavor": flavor(g), "trigger_kind": lower_trigger(g),
            "payload_kind": lower_payload(g)}
