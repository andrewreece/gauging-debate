/* GLOBALS */
var color = "red";				// Toggle, alternates blue/red output on cluster status report (testing only)
var check_interval = 30000;		// How frequently should we check up on a baking cluster?
var tweet_interval = 5000;		// How frequently should we pull down new data from SDB?
var interval_id, interval_id2;	// setInterval IDs (we need these to stop them)
var table_name = "tweettest";	// SDB table name (we may end up having more than one for LDA, sentiment, etc)
var ct = 0;						// ct and max_ct keep track of how many tweets we've displayed in our output
var max_ct = 40;				// "" ""

var bake_starting_msg = "Starting cluster...stand by for reporting<br />";
var bake_complete_msg = "CLUSTER IS FULLY BAKED. DATA COMING.";

function startPeeking(cid, interval) {
	/* Wraps setInterval() loop for checking on cluster status */
	interval_id = setInterval( 
					function() { ovenPeek(cid); }, 
					interval ); // We need interval_id to stop loop
}

function bakeIt(interval) {
	/* Spin up a new cluster, then initiate status check loop 
	   Note: /bake hits run.py, returns json status.  See run.py documentation for more.
	*/
	d3.json('/bake', function(data) {
		$('#bake-report').html( bake_starting_msg );
		cluster_id = data.Cluster.Id;
		startPeeking(cluster_id, interval); 
	});
}

function ovenPeek(cid) {
	/* Periodically check on currently-baking cluster, report on status */
		// testing
		// console.log('cid: '+cid);

	// /checkcluster hits run.py, see run.py for more
	d3.json('/checkcluster/'+cid, function(data) {

		// If RUNNING: May see old data for the first few returns, as new data hasn't gone to DB yet.
		// If WAITING: Should see only new data, cluster jobs have completed.
		if ((data.status=="WAITING") || (data.status=="RUNNING")) {

			getData(table_name); 		// pull down SDB data
			clearInterval(interval_id);	// stop cluster status check loop

			// Print "all done" status
			$('#bake-report').html( $('#bake-report').html()+"<br /><br />"+bake_complete_msg );

		// If NOT (RUNNING OR WAITING): Cluster is still starting up, report status and keep looping
		} else {

			$('#bake-report').html( function(d) { 

				color = (color == "red") ? "blue" : "red"; // Toggle print colors, no good reason
				span_front = "<br /><span style='color:"+color+";'>";
				span_back  = "</span>";
				new_html   = span_front + JSON.stringify(data) + span_back;
				return $('#bake-report').html()+new_html; 
			});
		}
	});
}

function getData(table_name) {
	/* Pulls data down from SDB, via Flask
			- Hits run.py, see run.py for more
			- Currently returns unprocessed tweets (only a bit of field filtering from Spark)
		This in mainly the output funciton for the initial PoC...we'll replace this soon.
		Note: ct, max_ct, tweet_interval are globals!
	*/
	$('#tweet').html("Working backwards from latest:<br />");
	interval_id2 = setInterval(  // We need interval_id2 to stop loop
		function() { 

			// max_ct is an arbitrary number, determines how many tweets to display as output
			if (ct < max_ct) {

				ct++;
				d3.json('/pull/'+table_name, function(error,data) {
					var data_len = d3.entries(data).length;
					var ix = data_len - 1;
					var new_html = "<br /><br />"+JSON.stringify(d3.entries(data)[ix].value);
					d3.select("#tweet").html( $('#tweet').html()+new_html );
				});
			// If we reach maximum number of test outputs, stop the loop, reset ct
			} else {

				clearInterval(interval_id2);
				console.log('stopping tweet pull');	
				ct = 0;
			}
		}, 
		tweet_interval); // How frequently should we check the database?
	
}

function display(d,back) {
	/* Once we start using D3, we may want to wrap our more complex display commands in a function 
		( Currently we just do all our output writes in getData() )
	*/

	//console.log(Object.keys(d));
	/*
	d3.selectAll(".tweet")
		.data(d3.entries(d))
		.enter()
		.append("div")
			.attr("class","tweet")
			.style("width","500px")
			.style("height","100px")
			.style("display",function(d,i) { if (i==(data_len-2)) {return "block";} else {return "none";}})
			.style("border","solid 2px maroon")
			.text( function(d,i) { return JSON.stringify(d.value); });
	*/
}

function terminateIt(cid) {
	/* Terminate EMR cluster (need cluster ID) */
	d3.text( '/terminate/'+cid, function(data) {
		// test output to console
		console.log(data);
		$('#terminate-report').text(JSON.stringify(data));
	});
}




/* 
	Below are HTML containers with onclick triggers to make things happen 
*/

// Get data from SDB
$('#pull').click( function() { $('#tweet').html("One moment <br />"); getData(table_name); } );

// Start a new cluster
$('#bake').click( function() { bakeIt(check_interval); } );

// Check on an existing cluster
$('#already-baking-check').click( function() { 
	var cluster_id = $('#cid').val(); // This button requires an ID to work properly. No error handling yet!
	$('#bake-report').text("Just a moment!...checking");
	startPeeking(cluster_id, check_interval);
} );

// Terminate cluster
$('#terminate').click( function() { terminateIt(); } );

