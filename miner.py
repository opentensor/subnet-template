import argparse
import os
import time
import traceback
from typing import Tuple

from bittensor.core.axon import Axon
from bittensor.core.config import Config
from bittensor.core.subtensor import Subtensor
from bittensor.utils.btlogging import logging
from bittensor_wallet import Wallet

from protocol import Dummy


class Miner:
    def __init__(self):
        self.subtensor = None
        self.wallet = None
        self.metagraph = None
        self.axon = None
        self.my_subnet_uid = None

        self.config = self.get_config()
        self.setup_logging()
        self.setup_bittensor_objects()

    def get_config(self):
        # Set up the configuration parser
        parser = argparse.ArgumentParser()
        # TODO: Add your custom miner arguments to the parser.
        parser.add_argument(
            "--custom",
            default="my_custom_value",
            help="Adds a custom value to the parser.",
        )
        # Adds override arguments for network and netuid.
        parser.add_argument(
            "--netuid", type=int, default=1, help="The chain subnet uid."
        )
        # Adds subtensor specific arguments.
        Subtensor.add_args(parser)
        # Adds logging specific arguments.
        logging.add_args(parser)
        # Adds wallet specific arguments.
        Wallet.add_args(parser)
        # Adds axon specific arguments.
        Axon.add_args(parser)
        # Parse the arguments.
        config = Config(parser)
        # Set up logging directory
        config.full_path = os.path.expanduser(
            "{}/{}/{}/netuid{}/{}".format(
                config.logging.logging_dir,
                config.wallet.name,
                config.wallet.hotkey_str,
                config.netuid,
                "miner",
            )
        )
        # Ensure the directory for logging exists.
        os.makedirs(config.full_path, exist_ok=True)
        return config

    def setup_logging(self):
        # Activate Bittensor's logging with the set configurations.
        logging(config=self.config, logging_dir=self.config.full_path)
        logging.info(
            f"Running miner for subnet: {self.config.netuid} on network: {self.config.subtensor.network} with config:"
        )
        logging.info(self.config)

    def setup_bittensor_objects(self):
        # Initialize Bittensor miner objects
        logging.info("Setting up Bittensor objects.")

        # Initialize wallet.
        self.wallet = Wallet(config=self.config)
        logging.info(f"Wallet: {self.wallet}")

        # Initialize subtensor.
        self.subtensor = Subtensor(config=self.config)
        logging.info(f"Subtensor: {self.subtensor}")

        # Initialize metagraph.
        self.metagraph = self.subtensor.metagraph(self.config.netuid)
        logging.info(f"Metagraph: {self.metagraph}")

        if self.wallet.hotkey.ss58_address not in self.metagraph.hotkeys:
            logging.error(
                f"\nYour miner: {self.wallet} is not registered to chain connection: {self.subtensor} \nRun 'btcli register' and try again."
            )
            exit()
        else:
            # Each miner gets a unique identity (UID) in the network.
            self.my_subnet_uid = self.metagraph.hotkeys.index(
                self.wallet.hotkey.ss58_address
            )
            logging.info(f"Running miner on uid: {self.my_subnet_uid}")

    def blacklist_fn(self, synapse: Dummy) -> Tuple[bool, str]:
        # Ignore requests from unrecognized entities.
        if synapse.dendrite.hotkey not in self.metagraph.hotkeys:
            logging.trace(
                f"Blacklisting unrecognized hotkey {synapse.dendrite.hotkey}"
            )
            return True, None
        logging.trace(
            f"Not blacklisting recognized hotkey {synapse.dendrite.hotkey}"
        )
        return False, None

    def dummy(self, synapse: Dummy) -> Dummy:
        # Simple logic: return the input value multiplied by 2.
        synapse.dummy_output = synapse.dummy_input * 2
        logging.info(
            f"Received input: {synapse.dummy_input}, sending output: {synapse.dummy_output}"
        )
        return synapse

    def setup_axon(self):
        # Build and link miner functions to the axon.
        self.axon = Axon(wallet=self.wallet, config=self.config)

        # Attach functions to the axon.
        logging.info("Attaching forward function to axon.")
        self.axon.attach(
            forward_fn=self.dummy,
            blacklist_fn=self.blacklist_fn,
        )

        # Serve the axon.
        logging.info(
            f"Serving axon on network: {self.config.subtensor.network} with netuid: {self.config.netuid}"
        )
        self.axon.serve(netuid=self.config.netuid, subtensor=self.subtensor)
        logging.info(f"Axon: {self.axon}")

        # Start the axon server.
        logging.info(f"Starting axon server on port: {self.config.axon.port}")
        self.axon.start()

    def run(self):
        self.setup_axon()

        # Keep the miner alive.
        logging.info(f"Starting main loop")
        step = 0
        while True:
            try:
                # Periodically update our knowledge of the network graph.
                if step % 60 == 0:
                    self.metagraph.sync()
                    log = (
                        f"Block: {self.metagraph.block.item()} | "
                        f"Incentive: {self.metagraph.I[self.my_subnet_uid]} | "
                    )
                    logging.info(log)
                step += 1
                time.sleep(1)

            except KeyboardInterrupt:
                self.axon.stop()
                logging.success("Miner killed by keyboard interrupt.")
                break
            except Exception:
                logging.error(traceback.format_exc())
                continue


# Run the miner.
if __name__ == "__main__":
    miner = Miner()
    miner.run()
