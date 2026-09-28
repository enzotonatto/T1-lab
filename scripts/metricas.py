#!/usr/bin/env python3
"""Extrai as métricas de C1/C2 de uma captura .pcapng usando o tshark.

Uso: python3 scripts/metricas.py capturas/c1.pcapng [--port 8080]

Métricas (itens 7 e 8 do relatório):
  - handshakes TCP completos (SYN, SYN-ACK e ACK vistos na mesma conexão)
  - total de pacotes, bytes totais (tamanho dos quadros) e tempo total
  - overhead de conexão: pacotes/bytes gastos só para abrir e fechar conexões
"""

import argparse
import shutil
import subprocess
import sys

FIN, SYN, RST, ACK = 0x01, 0x02, 0x04, 0x10


def read_packets(pcap, port):
    fields = ["tcp.stream", "tcp.flags", "tcp.len", "frame.len", "frame.time_epoch"]
    command = ["tshark", "-r", pcap, "-Y", f"tcp.port == {port}", "-T", "fields"]
    for field in fields:
        command += ["-e", field]
    output = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    packets = []
    for line in output.splitlines():
        stream, flags, tcp_len, frame_len, epoch = line.split("\t")
        packets.append({
            "stream": int(stream), "flags": int(flags, 16), "tcp_len": int(tcp_len),
            "frame_len": int(frame_len), "time": float(epoch),
        })
    return packets


def classify(packets):
    """Separa, por conexão, os pacotes de abertura (handshake) e de encerramento."""
    streams = {}
    for p in packets:
        streams.setdefault(p["stream"], []).append(p)

    handshakes = 0
    open_packets, close_packets = [], []
    for stream_packets in streams.values():
        saw_syn = saw_syn_ack = saw_ack = False
        closing = False
        for p in stream_packets:
            flags = p["flags"]
            if flags & SYN and not flags & ACK:
                saw_syn = True
                open_packets.append(p)
            elif flags & SYN and flags & ACK:
                saw_syn_ack = True
                open_packets.append(p)
            elif saw_syn_ack and not saw_ack and p["tcp_len"] == 0 and not flags & (FIN | RST):
                # terceiro passo do handshake: primeiro ACK puro depois do SYN-ACK
                saw_ack = True
                open_packets.append(p)
            elif flags & (FIN | RST):
                closing = True
                close_packets.append(p)
            elif closing and p["tcp_len"] == 0:
                # ACKs puros depois do primeiro FIN fazem parte do encerramento
                close_packets.append(p)
        if saw_syn and saw_syn_ack and saw_ack:
            handshakes += 1
    return len(streams), handshakes, open_packets, close_packets


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pcap")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if not shutil.which("tshark"):
        sys.exit("erro: tshark não encontrado (vem junto com o Wireshark)")

    packets = read_packets(args.pcap, args.port)
    if not packets:
        sys.exit(f"nenhum pacote TCP na porta {args.port} em {args.pcap}")
    connections, handshakes, open_packets, close_packets = classify(packets)

    total_bytes = sum(p["frame_len"] for p in packets)
    payload_bytes = sum(p["tcp_len"] for p in packets)
    duration = packets[-1]["time"] - packets[0]["time"]
    open_bytes = sum(p["frame_len"] for p in open_packets)
    close_bytes = sum(p["frame_len"] for p in close_packets)

    print(f"Captura: {args.pcap} (porta {args.port})")
    print(f"  Conexões TCP (streams):        {connections}")
    print(f"  Handshakes TCP completos:      {handshakes}")
    print(f"  Total de pacotes:              {len(packets)}")
    print(f"  Bytes totais (quadros):        {total_bytes}")
    print(f"  Bytes de payload TCP (HTTP):   {payload_bytes}")
    print(f"  Tempo total (1º ao último):    {duration * 1000:.3f} ms")
    print("  Overhead de conexão:")
    print(f"    abertura (SYN, SYN-ACK, ACK): {len(open_packets)} pacotes, {open_bytes} bytes")
    print(f"    encerramento (FIN/RST+ACKs):  {len(close_packets)} pacotes, {close_bytes} bytes")
    print(f"    total:                        {len(open_packets) + len(close_packets)} pacotes, "
          f"{open_bytes + close_bytes} bytes "
          f"({100 * (open_bytes + close_bytes) / total_bytes:.1f}% dos bytes)")


if __name__ == "__main__":
    main()
