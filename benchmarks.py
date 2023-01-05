import os
import time
import traceback
from collections import OrderedDict
from multiprocessing import Process

import pandas as pd

import torch
import torch.fx
import torchaudio
import torchtext
import torchvision

from olla import simulator, training_graph_optimizer, utils, visualizer
from olla.torch import torch_graph_importer

# Fix the environment to enable graphviz to work.
# del os.environ["LD_LIBRARY_PATH"]


class Benchmark:
    def load_model(
        self,
        model_name,
        mode,
        batch_size=32,
        device="cpu",
        profile=None,
        warm_up_iters=0,
        profile_iters=1,
        render_model=False,
    ):
        if model_name == "alexnet":
            model = torchvision.models.alexnet()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "conformer":
            input_dim = 80
            model = torchaudio.models.Conformer(
                input_dim=input_dim,
                num_heads=4,
                ffn_dim=128,
                num_layers=4,
                depthwise_conv_kernel_size=31,
            )
            lengths = torch.randint(1, 400, (batch_size,))  # (batch,)
            inp = torch.rand(
                batch_size, int(lengths.max()), input_dim
            )  # (batch, num_frames, input_dim)
            inputs = (inp, lengths)
        elif model_name == "deeplab":
            # Also try deeplabv3_mobilenet_v3_large()
            model = torchvision.models.segmentation.deeplabv3_resnet50()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "efficientnet":
            model = torchvision.models.efficientnet_b0()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "emformer":
            model = torchaudio.models.Emformer(
                512, 8, 2048, 20, 4, right_context_length=1
            )
            inp = torch.rand(batch_size, 400, 512)  # batch, num_frames, feature_dim
            lengths = torch.randint(1, 200, (batch_size,))  # batch
            inputs = (inp, lengths)
        elif model_name == "googlenet":

            class GoogleNetWrapper(torch.nn.Module):
                def __init__(self):
                    super(GoogleNetWrapper, self).__init__()
                    self.model = torchvision.models.googlenet()

                def forward(self, x):
                    rslt = self.model(x)
                    if self.model.training:
                        return torch.concat((rslt[0], rslt[1], rslt[2]), dim=-1)
                    else:
                        return rslt

            model = GoogleNetWrapper()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "inception":

            class InceptionWrapper(torch.nn.Module):
                def __init__(self):
                    super(InceptionWrapper, self).__init__()
                    self.model = torchvision.models.inception_v3()

                def forward(self, x):
                    rslt = self.model(x)
                    if self.model.training:
                        return torch.concat((rslt.logits, rslt.aux_logits), dim=-1)
                    else:
                        return rslt

            model = InceptionWrapper()
            # Need batch size > 1 when training
            min_batch_size = max(batch_size, 2) if mode == "train" else batch_size
            inputs = (torch.randn((min_batch_size, 3, 299, 299)),)
        elif model_name == "mnasnet":
            model = torchvision.models.mnasnet0_5()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "mobilenet":
            model = torchvision.models.mobilenet_v2(width_mult=0.25)
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "raft":
            model = torchvision.models.optical_flow.raft_small()
            inputs = (
                torch.randn((batch_size, 3, 520, 960)),
                torch.randn((batch_size, 3, 520, 960)),
            )
        elif model_name == "resnet":
            model = torchvision.models.resnet18()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "resnet50":
            model = torchvision.models.resnet50()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "resnet3d":
            model = torchvision.models.video.r3d_18()
            inputs = (torch.randn((batch_size, 3, 1, 112, 112)),)
        elif model_name == "bert":
            bert_base = torchtext.models.ROBERTA_BASE_ENCODER
            model = bert_base.get_model()
            transform = bert_base.transform()
            input_batch = ["x" * 512] * batch_size
            inputs = (
                torchtext.functional.to_tensor(transform(input_batch), padding_value=1),
            )
        elif model_name == "gpt2":
            from transformers import GPT2Tokenizer, GPT2Model
            class GPT2Wrapper(torch.nn.Module):
                def __init__(self):
                    super(GPT2Wrapper, self).__init__()
                    self.model = GPT2Model.from_pretrained('gpt2')

                def forward(self, x):
                    return self.model(x).last_hidden_state
            tokenizer = GPT2Tokenizer.from_pretrained('gpt2')
            text = "Replace me by any text you'd like."
            tokens = tokenizer.tokenize(text)
            indexed_tokens = tokenizer.convert_tokens_to_ids(tokens)
            inputs = torch.tensor([indexed_tokens])
            model = GPT2Wrapper()
        elif model_name == "megatron":
            from transformers import BertTokenizer, MegatronBertModel
            class MegatronWrapper(torch.nn.Module):
                def __init__(self):
                    super(MegatronWrapper, self).__init__()
                    self.model = MegatronBertModel.from_pretrained("nvidia/megatron-bert-cased-345m")

                def forward(self, x):
                    return self.model(x).last_hidden_state
            tokenizer = BertTokenizer.from_pretrained("nvidia/megatron-bert-cased-345m")
            text = "Replace me by any text you'd like."
            tokens = tokenizer.tokenize(text)
            indexed_tokens = tokenizer.convert_tokens_to_ids(tokens)
            inputs = torch.tensor([indexed_tokens])
            model = MegatronWrapper()
        elif model_name == "squeezenet":
            model = torchvision.models.squeezenet1_0()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "ssd":
            model = torchvision.models.detection.ssd300_vgg16()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "swin":
            model = torchvision.models.swin_t()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "transformer":
            model = torch.nn.Transformer(
                nhead=1, num_encoder_layers=1, num_decoder_layers=1
            )
            inputs = (
                torch.rand((10, batch_size, 512)),
                torch.rand((20, batch_size, 512)),
            )
        elif model_name == "transformer_dflt":
            model = torch.nn.Transformer()
            inputs = (
                torch.rand((10, batch_size, 512)),
                torch.rand((20, batch_size, 512)),
            )
        elif model_name == "vgg":
            model = torchvision.models.vgg11()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "vgg16":
            model = torchvision.models.vgg16()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "vgg19":
            model = torchvision.models.vgg19()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "vit":
            model = torchvision.models.vit_h_14()
            inputs = (torch.randn((batch_size, 3, 224, 224)),)
        elif model_name == "xlmr":
            xlmr_base = torchtext.models.XLMR_BASE_ENCODER
            model = xlmr_base.get_model()
            transform = xlmr_base.transform()
            input_batch = ["Hello world"] * batch_size
            inputs = (
                torchtext.functional.to_tensor(transform(input_batch), padding_value=1),
            )

        if mode == "eval":
            model.eval()

        if device != "cpu":
            model.to(device)
            # convert tuple to list so that we can modify it
            inputs = list(inputs)
            for idx, input in enumerate(inputs):
                inputs[idx] = input.to(device)
            inputs = tuple(inputs)

        optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
        importer = torch_graph_importer.TorchGraphImporter()
        g, pt_node_order = importer.import_via_aotautograd(
            model,
            *inputs,
            optimizer=optimizer,
            mode=mode,
            profile=profile,
            warm_up_iters=warm_up_iters,
            profile_iters=profile_iters,
        )
        g.name = f"{model_name}_{batch_size}_{mode}"

        # Prevent Pytorch from leaking memory
        del model
        del importer.fx_trace
        del importer
        torch.cuda.empty_cache()

        assert g.is_valid(verbose=True)

        # Dump the graph in the background
        if render_model:

            def dump_model():
                print("  PRINTING MODEL IN THE BACKGROUND", flush=True)
                with open(
                    "/tmp/"
                    + model_name
                    + "_"
                    + str(batch_size)
                    + "_raw_"
                    + mode
                    + ".txt",
                    mode="w",
                ) as f:
                    f.write(str(g))

                g.dump(
                    "/tmp/" + model_name + "_" + str(batch_size) + "_raw_" + mode,
                    format="svg",
                )

            p = Process(target=dump_model, name="dump_" + model_name, daemon=False)
            p.start()

        print("  CANONICALIZING MODEL", flush=True)
        g.canonicalize()
        print("  CONSTRAINING WEIGHT UPDATES", flush=True)
        g.constrain_weight_updates()
        print("  CONSTRAINING TENSOR GENERATORS", flush=True)
        g.constrain_tensor_generators()

        print("  CHECKING MODEL", flush=True)
        assert g.is_valid(verbose=True)

        # model_name = model.__class__.__name__
        # g.dump("/tmp/" + model_name + "_" + mode, format="svg")

        return g, pt_node_order

    def measure_pt_alloc_time(self, node_ordering, num_times=100):
        class MemLoc:
            def __init__(self, size):
                self.size = size
                self.address = None

            def run(self):
                if self.address:
                    torch.cuda.caching_allocator_delete(self.address)
                    self.address = None
                else:
                    self.address = torch.cuda.caching_allocator_alloc(self.size)

        edge_ref_counts = {}
        mem_sequence = []
        mem_locs = {}
        for n in node_ordering:
            for fanout in n.fanout:
                if fanout.size > 0:
                    edge_ref_counts[fanout] = len(fanout.sinks)
                    tensor = MemLoc(fanout.size)
                    mem_sequence.append(tensor)
                    mem_locs[fanout] = tensor

            for fanin in n.fanin:
                if fanin.size == 0:
                    continue
                edge_ref_counts[fanin] -= 1
                if edge_ref_counts[fanin] == 0:
                    tensor = mem_locs[fanin]
                    mem_sequence.append(tensor)

        start = time.time()
        for _ in range(num_times):
            for op in mem_sequence:
                op.run()
        stop = time.time()
        num_alloc_dealloc_pairs = num_times * len(mem_sequence) / 2
        return (stop - start, num_alloc_dealloc_pairs)

    # TODO: should we have run_profile() as a function here that measures fragmentation, instead of calculating or measuring fragmentation inside TorchGraphImporter? This would decouple profiling from TorchGraphImporter and hence make it easier to run the same script on AWS

    def run_simulation(self, g, node_order):
        start = time.time()
        s = simulator.Simulator(g)
        stop = time.time()
        simulated_mem_usage, mem_per_timestep = s.Simulate(node_order)
        return (simulated_mem_usage, stop - start)

    def run_node_ordering(self, g):
        start = time.time()
        s = training_graph_optimizer.Scheduler(g, rel_stop=0.005, timeout_s=1800)
        summary, schedule, mem_loc = s.ComputeOptimalSchedule(
            allow_swaps=False,
            max_spills=0,
        )
        stop = time.time()

        assert utils.validate_timeline(schedule)
        assert utils.validate_node_ordering(g, schedule)
        assert summary["peak_mem_usage"] == summary["required_memory"]
        # assert summary["peak_mem_usage"] <= simulated_mem_usage
        assert summary["total_data_swapped"] == 0

        node_ordering = utils.extract_node_ordering(g, schedule)
        return (summary["peak_mem_usage"], node_ordering, stop - start)

    def run_address_generation(self, g, node_order):
        start = time.time()
        s = training_graph_optimizer.Scheduler(
            g,
            rel_stop=0.001,
            timeout_s=1800,
            print_relaxation=True,
        )
        summary, schedule, mem_loc = s.ComputeOptimalSchedule(
            allow_swaps=False,
            max_spills=0,
            account_for_fragmentation=True,
            user_schedule=node_order,
        )
        stop = time.time()
        peak_mem_usage = summary["required_memory"]
        fragmentation = (peak_mem_usage - summary["peak_mem_usage"]) / peak_mem_usage
        assert utils.validate_timeline(schedule)
        assert utils.validate_address_allocation(mem_loc)
        assert summary["peak_mem_usage"] <= summary["required_memory"]
        assert summary["total_data_swapped"] == 0

        visualizer.draw_schedule(schedule, img_path="/tmp/" + g.name + ".png")

        return (peak_mem_usage, fragmentation, stop - start)

    def run_rematerialization(self, g, memory_budget):
        start = time.time()
        s = training_graph_optimizer.Scheduler(g, rel_stop=0.01, timeout_s=1800)
        summary, schedule, mem_loc = s.ComputeOptimalSchedule(
            allow_swaps=False,
            allow_rematerialization=True,
            mem_limit=memory_budget,
        )
        stop = time.time()
        extra_runtime = summary["rematerialization_time"]
        model_runtime = 0
        for n in g.nodes.values():
            if not n.time:
                continue
            model_runtime += n.time
        assert utils.validate_timeline(schedule)
        assert summary["peak_mem_usage"] == summary["required_memory"]
        assert summary["total_data_swapped"] == 0
        return (extra_runtime / model_runtime, stop - start)

    def run_spilling(self, g, memory_budget):
        start = time.time()
        s = training_graph_optimizer.Scheduler(g, rel_stop=0.01, timeout_s=1800)
        summary, schedule, mem_loc = s.ComputeOptimalSchedule(
            allow_swaps=True,
            allow_rematerialization=False,
            mem_limit=memory_budget,
        )
        stop = time.time()
        # TODO: replace bytes swapped to actual estimate of how much time it takes to
        # spill the data
        extra_runtime = summary["total_data_swapped"] / 16.0e9
        model_runtime = 0
        for n in g.nodes.values():
            if not n.time:
                continue
            model_runtime += n.time
        # print(f"MODEL TIME {model_runtime} vs SPILLING TIME {extra_runtime}")
        assert utils.validate_timeline(schedule)
        assert summary["peak_mem_usage"] == summary["required_memory"]
        return (extra_runtime / model_runtime, stop - start)


BENCHMARKS = {
    "alexnet": ["eval", "train"],
    "bert": ["eval", "train"],
    # "conformer": ["eval", "train"],  # fx can't trace the model
    # "deeplab": ["eval"],  # Train mode doesn't load
    "efficientnet": ["eval", "train"],
    # "emformer": ["eval", "train"],  # fx can't trace the model
    "googlenet": ["eval", "train"],
    "inception": ["eval", "train"],
    "mnasnet": ["eval", "train"],
    "mobilenet": ["eval", "train"],
    # "raft": ["eval", "train"],  # Model fails to load
    "resnet": ["eval", "train"],
    "resnet50": ["eval", "train"],
    "resnet3d": ["eval", "train"],
    "squeezenet": ["eval", "train"],
    # "ssd": ["eval"],  # Needs target in train mode
    # "swin": ["eval"],  # Model fails sanity checks
    "transformer": ["eval", "train"],
    "transformer_dflt": ["eval", "train"],
    "vgg": ["eval", "train"],
    "vgg16": ["eval", "train"],
    "vgg19": ["eval", "train"],
    "vit": ["eval", "train"],
    "xlmr": ["eval", "train"],
}


import argparse

parser = argparse.ArgumentParser(description="MemOpt Benchmarks")
# fmt: off
parser.add_argument("-b", "--batch-size", "--batch-sizes", nargs="+", type=int, default=[1, 32])
parser.add_argument("-m", "--model", "--models", nargs="+", type=str, default=BENCHMARKS.keys())
parser.add_argument("--mode", "--modes", nargs="+", type=str, choices=["eval", "train"], default=None)
# fmt: on
parser.add_argument("--generate-addresses", action="store_true")
parser.add_argument("--rematerialization", action="store_true")
parser.add_argument("--spilling", action="store_true")
parser.add_argument("--render-models", action="store_true")
parser.add_argument("--gpu-profile", action="store_true")
parser.add_argument("--profile-alloc-time", action="store_true")
parser.add_argument("--skip-simulation", action="store_true")
parser.add_argument("--skip-node-ordering", action="store_true")
parser.add_argument("--log-path", "--log_path", default="/tmp/opt4ml_benchmarks.csv")
parser.add_argument("--append-log", action="store_true")


if __name__ == "__main__":
    args = parser.parse_args()
    print(f"Running with args {args}")

    b = Benchmark()

    results = []

    for model in args.model:
        modes = BENCHMARKS[model] if not args.mode else args.mode
        for mode in modes:
            for batch_size in args.batch_size:
                result = OrderedDict(
                    [("model", model), ("mode", mode), ("batch_size", batch_size)]
                )
                print(
                    f"\nLOADING MODEL {model} IN {mode} MODE WITH BATCH SIZE {batch_size}",
                    flush=True,
                )
                device = "cpu"
                profile = []
                warm_up_iters = 1
                profile_iters = 10
                if args.rematerialization or args.spilling or args.gpu_profile:
                    profile.append("time")
                if args.gpu_profile:
                    torch.cuda.empty_cache()
                    profile.append("memory")
                    warm_up_iters = 0
                    profile_iters = 300
                    device = "cuda"

                if True: # try:
                    graph, pt_node_order = b.load_model(
                        model,
                        mode,
                        batch_size,
                        device=device,
                        profile=profile,
                        warm_up_iters=warm_up_iters,
                        profile_iters=profile_iters,
                        render_model=args.render_models,
                    )
                else: # except Exception as e:
                    print(f"  FAILED TO LOAD {model}, SKIPPING TO NEXT MODEL: {e}")
                    result["load_model.error"] = str(e).replace("\n", " ")
                    continue

                print(
                    f"BENCHMARKING MODEL {model} IN {mode} MODE WITH BATCH SIZE {batch_size}",
                    flush=True,
                )
                if args.gpu_profile:
                    print(
                        f"PROFILED MAX MEMORY FRAGMENTATION IS {graph.max_mem_fragmentation*100}% AND PROFILED PEAK MEMORY IS {graph.peak_reserved_bytes/(2**30)} GB"
                    )
                    result[
                        "profile.max_mem_fragmentation"
                    ] = graph.max_mem_fragmentation
                    result["profile.peak_reserved_bytes"] = graph.peak_reserved_bytes

                if not args.skip_simulation:
                    simulated_mem_usage, _ = b.run_simulation(
                        graph,
                        pt_node_order,
                    )
                    print(
                        f"  SIMULATED PEAK MEM USAGE IS {simulated_mem_usage}",
                        flush=True,
                    )
                    result["simulated_mem_usage"] = simulated_mem_usage

                if args.profile_alloc_time:
                    torch.cuda.empty_cache()
                    runtime, alloc_count = b.measure_pt_alloc_time(pt_node_order)
                    print(f"RAN {alloc_count} ALLOC/DEALLOC IN {runtime:.1f}s")
                    print(
                        f"AVERAGE TIME IS {1e6*runtime/alloc_count} USEC PER ALLOC/DEALLOC"
                    )
                    result["profile.alloc_runtime"] = runtime
                    result["profile.alloc_count"] = alloc_count

                if not args.skip_node_ordering:
                    assert (
                        not args.skip_simulation
                    ), "Simulation is required to run node ordering"
                    try:
                        peak_mem_usage, node_ordering, runtime = b.run_node_ordering(
                            graph
                        )
                        print(
                            f"  REORDERED NODES IN {runtime:.1f}s. PEAK MEM USAGE WAS {peak_mem_usage} (SAVED {(simulated_mem_usage - peak_mem_usage) / simulated_mem_usage * 100:.1f}%)",
                            flush=True,
                        )
                        result["node_ordering.runtime"] = runtime
                        result["node_ordering.peak_mem_usage"] = peak_mem_usage
                    except Exception as e:
                        print(f"  FAILED TO REORDER NODES: {e}", flush=True)
                        result["node_ordering.error"] = str(e).replace("\n", " ")
                        continue

                if args.generate_addresses:
                    assert (
                        not args.skip_simulation
                    ), "Simulation is required to run address generation"
                    assert (
                        not args.skip_node_ordering
                    ), "Node ordering is required to run address generation"
                    try:
                        (
                            peak_mem_usage,
                            fragmentation,
                            runtime,
                        ) = b.run_address_generation(graph, node_ordering)
                        print(
                            f"  GENERATED ADDRESSES IN {runtime:.1f}s. PEAK MEM USAGE WAS {peak_mem_usage}, FRAGMENTATION WAS {fragmentation * 100:.1f}%)",
                            flush=True,
                        )
                        result["address_generation.runtime"] = runtime
                        result["address_generation.fragmentation"] = fragmentation
                        result["address_generation.peak_mem_usage"] = peak_mem_usage
                    except Exception as e:
                        print(f"  FAILED TO GENERATE ADDRESSES: {e}", flush=True)
                        result["address_generation.error"] = str(e).replace("\n", " ")
                        traceback.print_exc()

                if args.rematerialization:
                    assert (
                        not args.skip_simulation
                    ), "Simulation is required to run rematerialization"
                    assert (
                        not args.skip_node_ordering
                    ), "Node ordering is required to run rematerialization"
                    try:
                        s = training_graph_optimizer.Scheduler(graph)
                        min_memory, _ = s.ComputeMinimumMemoryRequired()
                        for savings in [0.1, 0.25, 0.5, 0.75, 1.0]:
                            done = False
                            memory_budget = peak_mem_usage * (1.0 - savings)
                            if memory_budget < min_memory:
                                memory_budget = min_memory
                                savings = 1.0 - memory_budget / peak_mem_usage
                                done = True
                            overhead, runtime = b.run_rematerialization(
                                graph, memory_budget
                            )
                            print(
                                f"  PLANNED REMATERIALIZATION TO SAVE {savings*100}% MEMORY IN {runtime:.1f}s. INCREASED MODEL LATENCY BY {overhead*100:.3f}%)",
                                flush=True,
                            )
                            result[
                                f"rematerialization.savings_{savings}.overhead"
                            ] = overhead
                            result[
                                f"rematerialization.savings_{savings}.runtime"
                            ] = runtime
                            if done:
                                break
                    except Exception as e:
                        print(
                            f"  FAILED TO PLAN REMATERIALIZATION TO SAVE {savings*100}% MEMORY: {e}",
                            flush=True,
                        )
                        result[f"rematerialization.savings_{savings}.error"] = str(
                            e
                        ).replace("\n", " ")
                        traceback.print_exc()

                if args.spilling:
                    assert (
                        not args.skip_simulation
                    ), "Simulation is required to run spilling"
                    assert (
                        not args.skip_node_ordering
                    ), "Node ordering is required to run address spilling"

                    try:
                        graph.constrain_relative_ordering(node_ordering, linearize=True)
                        s = training_graph_optimizer.Scheduler(graph)
                        min_memory, _ = s.ComputeMinimumMemoryRequired()
                        for savings in [0.1, 0.25, 0.5, 0.75, 1.0]:
                            done = False
                            memory_budget = peak_mem_usage * (1.0 - savings)
                            if memory_budget < min_memory:
                                memory_budget = min_memory
                                savings = 1.0 - memory_budget / peak_mem_usage
                                done = True
                            overhead, runtime = b.run_spilling(graph, memory_budget)
                            print(
                                f"  PLANNED SPILLING TO SAVE {savings*100}% MEMORY IN {runtime:.1f}s. INCREASED MODEL LATENCY BY {overhead*100:.3f}%)",
                                flush=True,
                            )
                            result[f"spilling.savings_{savings}.overhead"] = overhead
                            result[f"spilling.savings_{savings}.runtime"] = runtime
                            if done:
                                break
                    except Exception as e:
                        print(
                            f"  FAILED TO PLAN SPILLING TO SAVE {savings*100}% MEMORY: {e}",
                            flush=True,
                        )
                        result[f"spilling.savings_{savings}.error"] = str(e).replace(
                            "\n", " "
                        )
                        traceback.print_exc()

                # Log result
                results.append(result)
                pd.DataFrame(results).fillna("").to_csv(
                    args.log_path,
                    mode="a" if args.append_log else "w",
                    header=not args.append_log,
                    index=False,
                )