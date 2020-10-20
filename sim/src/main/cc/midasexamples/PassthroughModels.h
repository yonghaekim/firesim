//See LICENSE for license details.

#include "simif.h"
#include "stdio.h"

class PassthroughModelDriver: virtual simif_t
{
public:
  PassthroughModelDriver(int argc, char** argv) {}
  int latency = 1;
  int length = 1 << 16;
  void run() {
    target_reset();
    step(length);
  }

};

class PassthroughModelIden_t: public PassthroughModelDriver {
  public:
    PassthroughModelIden_t(int argc, char** argv) : PassthroughModelDriver(argc, argv) {};
};
class PassthroughModelNested_t: public PassthroughModelDriver {
  public:
    PassthroughModelNested_t(int argc, char** argv) : PassthroughModelDriver(argc, argv) {};
};
class PassthroughModelBridgeSource_t: public PassthroughModelDriver {
  public:
    PassthroughModelBridgeSource_t(int argc, char** argv) : PassthroughModelDriver(argc, argv) {};
};
