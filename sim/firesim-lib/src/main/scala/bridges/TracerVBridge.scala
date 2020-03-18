//See LICENSE for license details
package firesim.bridges

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import freechips.rocketchip.config.{Parameters, Field}
import freechips.rocketchip.diplomacy.AddressSet
import freechips.rocketchip.util._
import freechips.rocketchip.rocket.TracedInstruction
import freechips.rocketchip.subsystem.RocketTilesKey
import freechips.rocketchip.tile.TileKey

import testchipip.{TileTraceIO, DeclockedTracedInstruction, TracedInstructionWidths}

import midas.widgets._
import testchipip.{StreamIO, StreamChannel}
import junctions.{NastiIO, NastiKey}
import TokenQueueConsts._

case class TracerVKey(
  insnWidths: TracedInstructionWidths, // Widths of variable length fields in each TI
  vecSize: Int // The number of insns in the traced insn vec (= max insns retired at that core) 
)


class TracerVTargetIO(insnWidths: TracedInstructionWidths, numInsns: Int) extends Bundle {
  val trace = Input(new TileTraceIO(insnWidths, numInsns))
}

class TracerVBridge(insnWidths: TracedInstructionWidths, numInsns: Int) extends BlackBox
    with Bridge[HostPortIO[TracerVTargetIO], TracerVBridgeModule] {
  val io = IO(new TracerVTargetIO(insnWidths, numInsns))
  val bridgeIO = HostPort(io)
  val constructorArg = Some(TracerVKey(insnWidths, numInsns))
  generateAnnotations()
}

object TracerVBridge {
  def apply(tracedInsns: TileTraceIO)(implicit p:Parameters): TracerVBridge = {
    val ep = Module(new TracerVBridge(tracedInsns.insnWidths, tracedInsns.numInsns))
    ep.io.trace := tracedInsns
    ep
  }
}

class TracerVBridgeModule(key: TracerVKey)(implicit p: Parameters) extends BridgeModule[HostPortIO[TracerVTargetIO]]()(p)
    with UnidirectionalDMAToHostCPU {
  val io = IO(new WidgetIO)
  val hPort = IO(HostPort(new TracerVTargetIO(key.insnWidths, key.vecSize)))

  val tFire = hPort.toHost.hValid && hPort.fromHost.hReady

  // Mask off valid committed instructions when under reset
  val traces = hPort.hBits.trace.insns.map({ unmasked =>
    val masked = WireDefault(unmasked)
    masked.valid := unmasked.valid && !hPort.hBits.trace.reset
    masked
  })
  private val pcWidth = traces.map(_.iaddr.getWidth).max
  private val insnWidth = traces.map(_.insn.getWidth).max

  //Program Counter trigger value can be configured externally
  val hostTriggerPCWidthOffset = pcWidth - p(CtrlNastiKey).dataBits
  val hostTriggerPCLowWidth = if (hostTriggerPCWidthOffset > 0) p(CtrlNastiKey).dataBits else pcWidth
  val hostTriggerPCHighWidth = if (hostTriggerPCWidthOffset > 0) hostTriggerPCWidthOffset else 0

  val hostTriggerPCStartHigh = RegInit(0.U(hostTriggerPCHighWidth.W))
  val hostTriggerPCStartLow = RegInit(0.U(hostTriggerPCLowWidth.W))
  attach(hostTriggerPCStartHigh, "hostTriggerPCStartHigh", WriteOnly)
  attach(hostTriggerPCStartLow, "hostTriggerPCStartLow", WriteOnly)
  val hostTriggerPCStart = Cat(hostTriggerPCStartHigh, hostTriggerPCStartLow)
  val triggerPCStart = RegInit(0.U(pcWidth.W))
  triggerPCStart := hostTriggerPCStart

  val hostTriggerPCEndHigh = RegInit(0.U(hostTriggerPCHighWidth.W))
  val hostTriggerPCEndLow = RegInit(0.U(hostTriggerPCLowWidth.W))
  attach(hostTriggerPCEndHigh, "hostTriggerPCEndHigh", WriteOnly)
  attach(hostTriggerPCEndLow, "hostTriggerPCEndLow", WriteOnly)
  val hostTriggerPCEnd = Cat(hostTriggerPCEndHigh, hostTriggerPCEndLow)
  val triggerPCEnd = RegInit(0.U(pcWidth.W))
  triggerPCEnd := hostTriggerPCEnd

  //Cycle count trigger
  val hostTriggerCycleCountWidthOffset = 64 - p(CtrlNastiKey).dataBits
  val hostTriggerCycleCountLowWidth = if (hostTriggerCycleCountWidthOffset > 0) p(CtrlNastiKey).dataBits else 64
  val hostTriggerCycleCountHighWidth = if (hostTriggerCycleCountWidthOffset > 0) hostTriggerCycleCountWidthOffset else 0

  val hostTriggerCycleCountStartHigh = RegInit(0.U(hostTriggerCycleCountHighWidth.W))
  val hostTriggerCycleCountStartLow = RegInit(0.U(hostTriggerCycleCountLowWidth.W))
  attach(hostTriggerCycleCountStartHigh, "hostTriggerCycleCountStartHigh", WriteOnly)
  attach(hostTriggerCycleCountStartLow, "hostTriggerCycleCountStartLow", WriteOnly)
  val hostTriggerCycleCountStart = Cat(hostTriggerCycleCountStartHigh, hostTriggerCycleCountStartLow)
  val triggerCycleCountStart = RegInit(0.U(64.W))
  triggerCycleCountStart := hostTriggerCycleCountStart

  val hostTriggerCycleCountEndHigh = RegInit(0.U(hostTriggerCycleCountHighWidth.W))
  val hostTriggerCycleCountEndLow = RegInit(0.U(hostTriggerCycleCountLowWidth.W))
  attach(hostTriggerCycleCountEndHigh, "hostTriggerCycleCountEndHigh", WriteOnly)
  attach(hostTriggerCycleCountEndLow, "hostTriggerCycleCountEndLow", WriteOnly)
  val hostTriggerCycleCountEnd = Cat(hostTriggerCycleCountEndHigh, hostTriggerCycleCountEndLow)
  val triggerCycleCountEnd = RegInit(0.U(64.W))
  triggerCycleCountEnd := hostTriggerCycleCountEnd

  val trace_cycle_counter = RegInit(0.U(64.W))

  //target instruction type trigger (trigger through target software)
  //can configure the trigger instruction type externally though simulation driver
  val hostTriggerStartInst = RegInit(0.U(insnWidth.W))
  val hostTriggerStartInstMask = RegInit(0.U(insnWidth.W))
  attach(hostTriggerStartInst, "hostTriggerStartInst", WriteOnly)
  attach(hostTriggerStartInstMask, "hostTriggerStartInstMask", WriteOnly)

  val hostTriggerEndInst = RegInit(0.U(insnWidth.W))
  val hostTriggerEndInstMask = RegInit(0.U(insnWidth.W))
  attach(hostTriggerEndInst, "hostTriggerEndInst", WriteOnly)
  attach(hostTriggerEndInstMask, "hostTriggerEndInstMask", WriteOnly)

  //trigger selector
  val triggerSelector = RegInit(0.U((p(CtrlNastiKey).dataBits).W))
  attach(triggerSelector, "triggerSelector", WriteOnly)

  //set the trigger
  //assert(triggerCycleCountEnd >= triggerCycleCountStart)
  val triggerCycleCountVal = RegInit(false.B)
  triggerCycleCountVal := (trace_cycle_counter >= triggerCycleCountStart) & (trace_cycle_counter <= triggerCycleCountEnd)

  val triggerPCValVec = RegInit(VecInit(Seq.fill(traces.length)(false.B)))
  traces.zipWithIndex.foreach { case (trace, i) =>
    when (trace.valid) {
      when (triggerPCStart === trace.iaddr) {
        triggerPCValVec(i) := true.B
      } .elsewhen ((triggerPCEnd === trace.iaddr) && triggerPCValVec(i)) {
        triggerPCValVec(i) := false.B
      }
    }
  }

  val triggerInstValVec = RegInit(VecInit(Seq.fill(traces.length)(false.B)))
  traces.zipWithIndex.foreach { case (trace, i) =>
    when (trace.valid) {
      when (!((hostTriggerStartInst ^ trace.insn) & hostTriggerStartInstMask).orR) {
        triggerInstValVec(i) := true.B
      } .elsewhen (!((hostTriggerEndInst ^ trace.insn) & hostTriggerEndInstMask).orR) {
        triggerInstValVec(i) := false.B
      }
    }
  }

  val trigger = MuxLookup(triggerSelector, false.B, Seq(
    0.U -> true.B,
    1.U -> triggerCycleCountVal,
    2.U -> triggerPCValVec.reduce(_ || _),
    3.U -> triggerInstValVec.reduce(_ || _)))

  //TODO: for inter-widget triggering
  //io.trigger_out.head <> trigger
  if (p(midas.TraceTrigger)) {
    BoringUtils.addSource(trigger, s"trace_trigger")
  }

  // DMA mixin parameters
  lazy val toHostCPUQueueDepth  = TOKEN_QUEUE_DEPTH
  lazy val dmaSize = BigInt((BIG_TOKEN_WIDTH / 8) * TOKEN_QUEUE_DEPTH)

  val uint_traces = (traces map (trace => Cat(trace.valid, trace.iaddr).pad(64))).reverse
  outgoingPCISdat.io.enq.bits := Cat(Cat(trace_cycle_counter,
                                         0.U((outgoingPCISdat.io.enq.bits.getWidth - Cat(uint_traces).getWidth - trace_cycle_counter.getWidth).W)),
                                     Cat(uint_traces))

  val tFireHelper = DecoupledHelper(outgoingPCISdat.io.enq.ready, hPort.toHost.hValid)
  hPort.toHost.hReady := tFireHelper.fire(hPort.toHost.hValid)
  // We don't drive tokens back to the target.
  hPort.fromHost.hValid := true.B

  outgoingPCISdat.io.enq.valid := tFireHelper.fire(outgoingPCISdat.io.enq.ready, trigger)

  when (tFireHelper.fire) {
    trace_cycle_counter := trace_cycle_counter + 1.U
  }

  attach(outgoingPCISdat.io.deq.valid && !outgoingPCISdat.io.enq.ready, "tracequeuefull", ReadOnly)
  genCRFile()
  override def genHeader(base: BigInt, sb: StringBuilder) {
    import CppGenerationUtils._
    val headerWidgetName = getWName.toUpperCase
    super.genHeader(base, sb)
    emitClockDomainInfo(headerWidgetName, sb)
  }
}
