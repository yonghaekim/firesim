// See LICENSE for license details.

#include "TestHarness.h"
#include "bridges/plusargs.h"
#include "bridges/token_hashers.h"

#include <iomanip>
#include <iostream>

#define HEX32_STRING(n) std::setfill('0') << std::setw(8) << std::hex << (n) << std::dec

/**
 * @brief Token Hashers Bridge Driver Test
 *
 * This test copies the cramework from PlusArgsModule.h
 * parses `+plusargs_test_key` (given by TutorialSuite.scala)
 * and asserts for the correct values
 */
class TestTokenHashersModule : public TestHarness {
private:
  token_hashers_t &hasher;
public:

  /**
   * Constructor.
   *
   * @param [in] argc The standard argc from main()
   * @param [in] argv The standard argv from main()
   */
  TestTokenHashersModule(const std::vector<std::string> &args, simif_t &simif)
      : TestHarness(args, simif),
      hasher(get_bridge<token_hashers_t>()) 
      
      {
    signal_search();
    hasher.info();

    XORHash32 a;
    std::cout << HEX32_STRING(a.next(0xf000)) << "\n";
    std::cout << HEX32_STRING(a.next(0xf001)) << "\n";
    std::cout << HEX32_STRING(a.next(0xf002)) << "\n";
  }

/**
 * search through the signals recorded by token_hashers 
*/
  void signal_search() {

    auto get_one_idx = [&](const std::string &name, size_t &found_idx) {
      const auto find_idx = hasher.search("PeekPokeBridgeModule", name);
      assert(find_idx.size() == 1 && "Hasher reports multiple signals found, expecting only one");
      found_idx = find_idx[0];
      std::cout << name << " was found at idx: " << found_idx << "\n";
    };

    for (size_t i = 0; i < count; i++) {
      get_one_idx(names[i], hash_idx[i]);
    }
  }

  /**
   * Run. Check our assertions before the first step, as well as 7 more times.
   * These extra assertion make sure that the value does not change or glitch.
   */
  void run_test() override {


    hasher.set_params(0,0);
    // const int loops = choose_params();
    const int loops = 16;


    // plusargsinator.init();
    target_reset();
    for (int i = 0; i < loops; i++) {
      // validate before first tick and for a few after (b/c of the loop)
      // validate();

      const uint32_t writeValue = 0xf000 | i;
      poke("io_writeValue", writeValue);
      const uint32_t readValue = peek("io_readValue");
      const uint32_t readValueFlipped = peek("io_readValueFlipped");

      std::cout << "step " << i << " wrote " << HEX32_STRING(writeValue) << " read: " << HEX32_STRING(readValue) << "  " << HEX32_STRING(readValueFlipped) << "\n";

      step(1);
    }

    // hasher.get();
    // hasher.print();
    std::cout << hasher.get_csv_string();

    // hasher.write_csv_file("test-run.csv");
  }

private:
  constexpr static size_t count = 3;
  constexpr static std::array<const char *, count> names = {
      "io_writeValue", "io_readValue", "io_readValueFlipped"};
  std::array<size_t, count> hash_idx;
  std::array<XORHash32, count> expected;
};

TEST_MAIN(TestTokenHashersModule)
